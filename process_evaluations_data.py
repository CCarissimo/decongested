import numpy as np
from scipy.stats import entropy


if __name__ == "__main__":
    from dqn_grid_online import compose_path
    from pathlib import Path
    from pre_process_data import extract_normalized_trip_lengths_per_agent, \
        extract_transitions_from_data, extract_moving_average_from_data, \
        count_state_action_visits, calculate_driver_entropy
    import pickle
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('n_iter', type=int)
    parser.add_argument('next_destination_method', type=str)
    parser.add_argument('exploration_method', type=str)
    parser.add_argument('save_path', type=str)  # main directory
    parser.add_argument('grid_name', type=str)  # subdirectory
    parser.add_argument('centralized_ratio', type=float)
    parser.add_argument('internal_save_path', type=str)  # where to save the processed data
    parser.add_argument('--iot_nodes', action="store_true", default=False)
    parser.add_argument('--with_agent_ids', action="store_true", default=False)
    parser.add_argument('--non_stationary', action="store_true", default=False)
    args = parser.parse_args()

    path = compose_path(
        save_path=args.save_path,
        grid_name=args.grid_name,
        n_observations=25,
        exploration_method=args.exploration_method,
        agents_see_iot_nodes=args.iot_nodes,
        n_agents=100,
        next_destination_method=args.next_destination_method,
        n_iter=args.n_iter,
        batch_size=64,
        eps_start=0.5,
        eps_end=0.05,
        gamma=0.9,
        lr=1e-2
    )

    evaluations_path = f"{path}/evaluations{'_with_ids' if args.with_agent_ids else ''}"
    # evaluate trips
    with open(f"{evaluations_path}/trips_evaluate_ratio_{args.centralized_ratio}", "rb") as file:
        trips = pickle.load(file)

    per_agent_interpolated_trip_lengths, _, _ = extract_normalized_trip_lengths_per_agent(trips, n_agents=100)
    system_interpolated_trip_lengths = per_agent_interpolated_trip_lengths.mean(0)
    average_trip_length_during_testing = system_interpolated_trip_lengths.mean()
    variance_trip_length_during_testing = system_interpolated_trip_lengths.var()

    del trips

    # evaluate data
    with open(f"{evaluations_path}/data_evaluate_ratio_{args.centralized_ratio}", "rb") as file:
        data = pickle.load(file)

    transitions = extract_transitions_from_data(data)
    state_action_visits = count_state_action_visits(transitions, size=4, n_actions=4, n_agents=100)
    empirical_entropy = calculate_driver_entropy(state_action_visits)
    average_empirical_entropy_testing = np.mean(
        np.array([driver_entropy for driver_entropy in empirical_entropy.values()]))

    moving_average = extract_moving_average_from_data(data)
    moving_average_all_testing = np.array(moving_average).mean()

    del data

    row = {
        "grid": args.grid_name,
        "dex": args.next_destination_method,
        "exploration": args.exploration_method,
        "with_ids": int(args.with_agent_ids),
        "epsilon": 0,
        "iot-nodes": args.iot_nodes,
        "ratio": args.centralized_ratio,
        "evaluate": average_trip_length_during_testing,
        "evaluate_var": variance_trip_length_during_testing,
        "ma_all_testing": moving_average_all_testing,
        "entropy_testing": average_empirical_entropy_testing,
    }

    Path(args.internal_save_path).mkdir(parents=True, exist_ok=True)
    with open(f"{args.internal_save_path}/row_{args.grid_name}_{args.next_destination_method}_{args.exploration_method}"
              f"_{args.iot_nodes}_{args.centralized_ratio}_{args.with_agent_ids}", "wb") as file:
        pickle.dump(row, file)
