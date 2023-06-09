import torch
import pickle

from dqn_agent import model, ReplayMemory

from environment import roadGridOnline

import numpy as np
from pathlib import Path
import copy
import plotting
from grids import generator_functions

from dqn_grid_online import compose_path
from dqn_grid_train_centralized import add_randomized_ids_to_transitions, add_randomized_id_to_state

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def evaluate_trained_models(n_iter, next_destination_method="simple", exploration_method="random", agents_see_iot_nodes=True,
                            save_path="experiments", grid_name="uniform", train=False, centralized_ratio=0, non_stationary=False,
                            use_agent_ids=False, experiment_name=""):
    SIZE = 4

    G = generator_functions.generate_4x4_grids(costs=grid_name, seed=0)

    print([node for node in G.nodes()])

    ENVIRONMENT = f"4x4_grid_{grid_name}"
    Path(f"{save_path}/{ENVIRONMENT}").mkdir(parents=True, exist_ok=True)

    N_AGENTS = 100
    N_ACTIONS = 4
    N_STATES = 4
    N_OBSERVATIONS = int(SIZE * 2) * 2 + 2 * N_ACTIONS + 1  # state space
    EPISODE_TIMEOUT = 16
    NEXT_DESTINATION_METHOD = next_destination_method

    AGENTS_SEE_IOT_NODES = agents_see_iot_nodes

    N_ITER = n_iter
    BATCH_SIZE = 64
    GAMMA = 0.9
    EPS_START = 0.5
    EPS_END = 0.05
    EPS_DECAY = N_ITER / 10000  # larger is slower
    TAU = 0.05  # TAU is the update rate of the target network
    LR = 1e-2  # LR is the learning rate of the AdamW optimizer
    EXPLORATION_METHOD = exploration_method
    AGENTS = f"dqn_{N_OBSERVATIONS}_exploration_{EXPLORATION_METHOD}_iot_{AGENTS_SEE_IOT_NODES}"
    TRAINING_SETTINGS = f"N{N_AGENTS}_dex-{NEXT_DESTINATION_METHOD}_I{N_ITER}_B{BATCH_SIZE}_EXP{EPS_START - EPS_END}_G{GAMMA}_LR{LR}"
    PATH = f"{save_path}/{ENVIRONMENT}/{AGENTS}_{TRAINING_SETTINGS}"
    Path(PATH).mkdir(parents=True, exist_ok=True)

    print(PATH)

    PRETRAINED_MODEL = f"{PATH}/drivers"
    with open(PRETRAINED_MODEL, "rb") as file:
        drivers = pickle.load(file)
    for driver in drivers.values():
        driver.steps_done = 0
        driver.memory = ReplayMemory(10000)
        driver.device = DEVICE
        driver.apply_device(DEVICE)

    with open(f"{PATH}/agent{'_with_ids' if use_agent_ids else ''}", "rb") as file:
        agent = pickle.load(file)
    centralized_mask = np.random.binomial(n=1, p=centralized_ratio, size=N_AGENTS).astype(bool)

    data = {}

    env = roadGridOnline(
        graph=G,
        n_agents=N_AGENTS,
        n_actions=N_ACTIONS,
        size=SIZE,
        next_destination_method=NEXT_DESTINATION_METHOD,
        agents_see_iot_nodes=AGENTS_SEE_IOT_NODES
    )

    TRANSIENT_LENGTH = 50000
    EVALUATE_ITER = 100000 + TRANSIENT_LENGTH
    stationarity_switch = True
    possible_ids = np.linspace(0, 0.99, N_AGENTS)
    state, info, base_state, agents_at_base_state = env.reset()

    t = 0
    switches = [15000, 17500, 20000, 22500, 25000, 27500]
    threshold = switches.pop(0)
    seed = 0
    #for t in range(EVALUATE_ITER):
    while env.T.max() < 30000:

        independent_agents = agents_at_base_state * np.logical_not(centralized_mask)
        independent_actions = {n:
                                   driver.select_action(
                                       state=torch.tensor(state[n], dtype=torch.float32, device=DEVICE),
                                       EPS_END=0.05,
                                       EPS_START=0.05,
                                       EPS_DECAY=1,
                                       method="random",
                                       neighbour_beliefs=None).unsqueeze(0)
                               for n, driver in enumerate(drivers.values()) if independent_agents[n]
                               }

        agents_that_receive_centralized_recommendation = agents_at_base_state * centralized_mask
        dependent_actions = {n:
                                 agent.select_action(
                                     state=torch.tensor(
                                         add_randomized_id_to_state(state[int(n)], possible_ids) if use_agent_ids else state[int(n)],
                                         dtype=torch.float32, device=DEVICE),
                                     EPS_END=0.05,
                                     EPS_START=0.05,
                                     EPS_DECAY=1,
                                     method="random",
                                     neighbour_beliefs=None).unsqueeze(0)
                             for n, driver in enumerate(drivers.values()) if
                             agents_that_receive_centralized_recommendation[n]
                             }

        dependent_actions.update(independent_actions)
        action_list = [dependent_actions[i].to(DEVICE) for i, n in enumerate(agents_at_base_state) if agents_at_base_state[i]]
        A = torch.cat(action_list)
        actions = A.cpu().numpy()

        state, base_state, agents_at_base_state, transitions, done = env.step(actions, drivers)

        if train and env.T.max() > 10000:
            for n, transition in transitions:
                drivers[n].memory.push(
                    transition["state"].to(DEVICE),
                    transition["action"].to(DEVICE),
                    transition["next_state"].to(DEVICE),
                    transition["reward"].to(DEVICE))
                drivers[n].optimize_model()

            for n, transition in transitions:
                if use_agent_ids:
                    transition = add_randomized_ids_to_transitions(transition=transition, possible_ids=possible_ids, device=DEVICE)
                agent.memory.push(
                    transition["state"].to(DEVICE),
                    transition["action"].to(DEVICE),
                    transition["next_state"].to(DEVICE),
                    transition["reward"].to(DEVICE))
            agent.optimize_model()  # un-indented to train only once, and not len(transitions) times

        if non_stationary and env.T.max() >= threshold and stationarity_switch:
            seed += 1
            env.change_underlying_graph(new_graph=generator_functions.generate_4x4_grids(costs="random", seed=seed))
            # stationarity_switch = False  # such that this is triggered only once
            if len(switches) > 0:
                threshold = switches.pop(0)
            else:
                threshold = 100000  #larger than will be reached

        if t % 100 == 0:
            print("step: ", t, "welfare: ", env.average_trip_time, "success rate:", env.reached_destinations.mean(),
                  "exploration rate:", drivers[0].eps_threshold)

        # SAVE PROGRESS DATA[agents]
        data[t] = {
            "T": env.T.max(),
            # "S": env.S,
            "average_trip_time": env.average_trip_time,
            "transitions": transitions,
        }
        t += 1

    PATH = f"{PATH}/evaluations{'_with_ids' if use_agent_ids else ''}{'_non_stationary' if non_stationary else ''}/{experiment_name}"
    Path(PATH).mkdir(parents=True, exist_ok=True)

    with open(f"{PATH}/data_evaluate_ratio_{centralized_ratio}", "wb") as file:
        pickle.dump(data, file)

    # for driver in drivers.values():
    #     driver.memory = ReplayMemory(10000)  # clear buffer for storage
    # with open(f"{PATH}/drivers", "wb") as file:
    #     pickle.dump(drivers, file)

    with open(f"{PATH}/trips_evaluate_ratio_{centralized_ratio}", "wb") as file:
        pickle.dump(dict(env.trips), file)  # calling `dict' to offset defaultdict lambda for pickling

    with open(f"{PATH}/trajectory_evaluate_ratio_{centralized_ratio}", "wb") as file:
        pickle.dump(env.trajectory, file)

    print(PATH)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('n_iter', type=int)
    parser.add_argument('next_destination_method', type=str)
    parser.add_argument('exploration_method', type=str)
    parser.add_argument('save_path', type=str)
    parser.add_argument('grid_name', type=str)
    parser.add_argument('centralized_ratio', type=float)
    parser.add_argument('experiment_name', type=str)
    parser.add_argument('--iot_nodes', action="store_true", default=False)
    parser.add_argument('--train', action="store_true", default=False)
    parser.add_argument('--non_stationary', action="store_true", default=False)
    parser.add_argument('--with_ids', action="store_true", default=False)
    args = parser.parse_args()

    evaluate_trained_models(
        n_iter=args.n_iter,
        next_destination_method=args.next_destination_method,
        exploration_method=args.exploration_method,
        agents_see_iot_nodes=args.iot_nodes,
        save_path=args.save_path,
        grid_name=args.grid_name,
        train=args.train,
        centralized_ratio=args.centralized_ratio,
        non_stationary=args.non_stationary,
        use_agent_ids=args.with_ids,
        experiment_name=args.experiment_name
    )
