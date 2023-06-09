import pandas as pd
import pickle
import glob


def unify_pickle_rows_into_dataframe(path, multirow=False):

    rows = []

    for file_path in glob.glob(pathname=f"{path}/row_*"):
        with open(file_path, "rb") as file:
            row = pickle.load(file)

        if multirow:
            for element in row:
                rows.append(element)
        else:
            rows.append(row)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('save_path', type=str)  # main directory
    parser.add_argument('internal_save_path', type=str)  # where to save the processed data
    parser.add_argument('output_filename', type=str)  # name of the csv file
    parser.add_argument('--multirow', action="store_true", default=False)
    args = parser.parse_args()

    df = unify_pickle_rows_into_dataframe(args.save_path, args.multirow)

    path = f"{args.internal_save_path}/{args.output_filename}"

    df.to_csv(path)
    print(f"save csv successful to {path}")
