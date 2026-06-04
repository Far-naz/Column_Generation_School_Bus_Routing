from module.stop_point import Stop, STOP_TYPE
import pandas as pd


def read_all_stops():
    stops = [
        Stop(student_id = 1, name = 1, id=1, stop_type=STOP_TYPE.SCHOOL, lat=5, lon=7),
        Stop(student_id = 2, name = 2, id=2, stop_type=STOP_TYPE.STUDENT, lat=3, lon=7),
        Stop(student_id = 3, name = 3, id=3, stop_type=STOP_TYPE.STUDENT, lat=2, lon=8),
        Stop(student_id = 4, name = 4, id=4, stop_type=STOP_TYPE.STUDENT, lat=7, lon=11),
        Stop(student_id = 5, name = 5, id=5, stop_type=STOP_TYPE.STUDENT, lat=8, lon=10),
        Stop(student_id = 6, name = 6, id=6, stop_type=STOP_TYPE.STUDENT, lat=10, lon=12),
        Stop(student_id = 7, name = 7, id=7, stop_type=STOP_TYPE.STUDENT, lat=8, lon=17),
        Stop(student_id = 8, name = 8, id=8, stop_type=STOP_TYPE.STUDENT, lat=15, lon=10),
        Stop(student_id = 9, name = 9, id=9, stop_type=STOP_TYPE.BUSSTOP, lat=2, lon=12),
        Stop(student_id = 10, name = 10, id=10, stop_type=STOP_TYPE.BUSSTOP, lat=4, lon=16),
        Stop(student_id = 11, name = 11, id=11, stop_type=STOP_TYPE.BUSSTOP, lat=7, lon=13),
        Stop(student_id = 12, name = 12, id=12, stop_type=STOP_TYPE.BUSSTOP, lat=11, lon=13),
        Stop(student_id = 13, name = 13, id=13, stop_type=STOP_TYPE.BUSSTOP, lat=12, lon=7),
        Stop(student_id = 14, name = 14, id=14, stop_type=STOP_TYPE.BUSSTOP, lat=14, lon=10),
        Stop(student_id = 15, name = 15, id=15, stop_type=STOP_TYPE.SCHOOL,lat=5, lon=7)
    ]
    
    return stops


def read_bus_stops(data_file: str, lst_index: int) -> list[Stop]:
    stops = []
    # csv file with header: StopId,StopAbbr,StopName,Lat,Lon
    df = pd.read_csv(data_file)
    idx = lst_index + 1
    for _, row in df.iterrows():
        stop_id = idx
        idx += 1
        name = row["StopId"]
        lat = float(row["Lat"]) / 1e6
        lon = float(row["Lon"]) / 1e6
        stop = Stop(id=stop_id, stop_type=STOP_TYPE.BUSSTOP, lat=lat, lon=lon, name=name, student_id=-1)
        stops.append(stop)

    return stops


def get_schools(data_file: str, school_id: int ) -> list[Stop]:
    schools = []
    # csv file with header: LocId,LocName,Lon,Lat,OnStreet,City,ZipCode
    df = pd.read_csv(data_file)
    if school_id is not None:
        df = df[df["LocId"] == school_id]
    for _, row in df.iterrows():
        school_id = 0
        name = row["LocId"]
        lat = float(row["Lat"]) / 1e6
        lon = float(row["Lon"]) / 1e6
        school = Stop(
            id=school_id, stop_type=STOP_TYPE.SCHOOL, lat=lat, lon=lon, name=name, student_id=-1
        )
        schools.append(school)

    return schools


def read_students_locations(data_file: str, school_id: int) -> list[Stop]:
    students = []
    # csv file with header ClientId,AddrId,SubscriptionTemplateId,LocName,schooltype,LocId,schoollat,schoollon,FromAddrType,ToAddrType,adresslat,adresslon,grade,requestedtimeinbound,requestedtimeoutbound
    df = pd.read_csv(data_file)
    df_school = df[df["LocId"] == school_id]
    idx = 1
    for _, row in df_school.iterrows():
        student_id = idx
        name = row["ClientId"]
        lat = float(row["adresslat"]) / 1e6
        lon = float(row["adresslon"]) / 1e6
        student = Stop(
            id=student_id, stop_type=STOP_TYPE.STUDENT, lat=lat, lon=lon, name=name, student_id=student_id
        )
        students.append(student)
        idx += 1

    return students
