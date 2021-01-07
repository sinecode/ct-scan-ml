import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from scipy import ndimage
from tqdm import tqdm

from utils import read_dcm, volume_to_example
from config import (
    LIDC_NUM_NODULES_TFRECORD,
    RESIZED_SCAN_SHAPE,
    SCAN_SHAPE,
)


def read_lidc_size_report(csv_file):
    """
    Read the CSV file obtained from  http://www.via.cornell.edu/lidc/

    Return a Pandas DataFrame with columns (case, scan, num_nodules)
    """
    df = pd.read_csv(csv_file, dtype={"case": str, "scan": str})
    df["noduleIDs"] = (
        df[["nodIDs", "Unnamed: 10", "Unnamed: 11", "Unnamed: 12"]]
        .fillna("")
        .values.tolist()
    )
    df["noduleIDs"] = df["noduleIDs"].apply(lambda x: [e for e in x if e])
    df = (
        df.drop(
            columns=[
                "volume",
                "eq. diam.",
                "nodIDs",
                "x loc.",
                "y loc.",
                "slice no.",
                "noduleIDs",
                "Unnamed: 8",
                "Unnamed: 10",
                "Unnamed: 11",
                "Unnamed: 12",
                "Unnamed: 13",
                "Unnamed: 14",
                "Unnamed: 15",
            ]
        )
        .groupby(["case", "scan"])
        .count()
        .reset_index()
        .rename(
            columns={
                "roi": "num_nodules",
            }
        )
    )
    assert len(df) == 876
    return df


def preprocess_scan(scan):
    z, y, x = scan.shape
    target_z, target_y, target_x, _ = RESIZED_SCAN_SHAPE
    scan = ndimage.zoom(
        scan, (target_z / z, target_y / y, target_x / x), order=5
    )
    scan = scan.astype(np.float32)
    scan = scan[8:-8, 32:-32, 16:-16]
    scan = np.expand_dims(scan, axis=-1)  # add the channel dimension
    assert scan.shape == SCAN_SHAPE
    return scan


def main():
    parser = argparse.ArgumentParser(
        description="Divide the lung in two tfrecords files: num nodules < 25 and otherwise.",
    )
    parser.add_argument(
        "data_dir",
        help="Directory containing all the DCM files downloaded from https://wiki.cancerimagingarchive.net/display/Public/LIDC-IDRI",
    )
    parser.add_argument(
        "csv_file",
        help="CSV file obtained from http://www.via.cornell.edu/lidc",
    )

    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    nodules_df = read_lidc_size_report(args.csv_file)
    processed_scans = set()
    with tf.io.TFRecordWriter(LIDC_NUM_NODULES_TFRECORD) as writer:
        for row in tqdm(nodules_df.itertuples(), total=len(nodules_df.index)):
            case = row.case
            scan_id = row.scan
            if (case, scan_id) in processed_scans:
                print(
                    f"WARNING ({scan_id=} {case=}): "
                    "Scan already processed. Skipping this entry ..."
                )
                continue
            dcm_dir_glob = list(
                data_dir.glob(f"LIDC-IDRI-{case}/*/{scan_id}.*/")
            )
            if len(dcm_dir_glob) == 0:
                print(
                    f"WARNING ({scan_id=} {case=}): "
                    "Scan not found. Skipping this scan ..."
                )
                continue
            if len(dcm_dir_glob) > 1:
                print(
                    f"WARNING ({scan_id=} {case=}): "
                    "Found multiple scans with same ids. Skipping this scan ..."
                )
                continue
            dcm_dir = dcm_dir_glob[0]
            scan = read_dcm(dcm_dir, reverse_z=False)
            scan = preprocess_scan(scan)
            scan_example = volume_to_example(scan, label=row.num_nodules)
            writer.write(scan_example.SerializeToString())
            processed_scans.add((case, scan_id))


if __name__ == "__main__":
    main()