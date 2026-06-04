from module.stop_point import Stop, STOP_TYPE
import pandas as pd
from config import SCHOOL_FILE


def _read_school_from_file(data_file: str, school_id: int) -> Stop:
    if school_id is None:
        return ValueError("school_id is not provided.")

    # csv file with header: LocId,LocName,Lon,Lat,OnStreet,City,ZipCode
    df = pd.read_csv(data_file)

    df_filtered = df[df["LocId"] == school_id]
    lat = float(df_filtered.iloc[0]["Lat"]) / 1e6
    lon = float(df_filtered.iloc[0]["Lon"]) / 1e6
    loc_id = df_filtered.iloc[0]["LocId"]

    return Stop(
        lat=lat, lon=lon, id=0, second_id=0, stop_type=STOP_TYPE.SCHOOL, name=loc_id, student_id=0
    )


def get_school(school_id=33337) -> Stop:
    # if data_source == DataSource.TOY:
    #    school = Stop
    #    return school
    # if data_source == DataSource.REAL:
    school = _read_school_from_file(SCHOOL_FILE, school_id)
    return school
