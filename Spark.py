 #coding=utf-8
from __future__ import print_function
from pyspark import SparkConf
from pyspark import SparkContext
from Transportation import *
import json
from pyspark.files import SparkFiles

class Spark():
    def __init__(self):
        self.sc = None
        self.sorted_user_record_list = None
        self.file_path = None
        self.input_data = None
    def connect(self):
        self.connectToSchool()

    def setLocalInputFile(self,inputFile):
        self.input_data = self.sc.parallelize(inputFile)



    def connectToSchool(self):
        conf=SparkConf()
        conf.setMaster("spark://namenode:7077")
        conf.setAppName("off-peak")
        conf.set("spark.executor.memory", "54g")
        conf.set("spark.executor.cores", "8")
        conf.set("spark.scheduler.mode", "FAIR")
        sc = SparkContext(conf=conf)
        sc.addPyFile("Module/Shapely-1.6b4.zip")
        sc.addFile("exploring/Spark.py")
        sc.addFile("exploring/Transportation.py")
        sc.addFile("exploring/Record.py")
        sc.addFile("exploring/TransRegions.py")
        sc.addFile("exploring/__init__.py")
        sc.addFile('exploring/SparkLocalMain.py')
        sc.addFile('exploring/Route.py')
        self.sc =sc

    def connectToDesktop(self):
        conf=SparkConf()
        conf.setMaster("spark://namenode:7077")
        conf.setAppName("off-peak")
        conf.set("spark.executor.memory", "24g")
        conf.set("spark.executor.cores", "12")
        conf.set("spark.scheduler.mode", "FAIR")
        sc = SparkContext(conf=conf)
        sc.addFile("Spark.py")
        sc.addFile("Transportation.py")
        sc.addFile("Record.py")
        sc.addFile("TransRegions.py")
        sc.addFile("__init__.py")
        sc.addFile('SparkLocalMain.py')
        self.sc = sc

    def setInputData(self,input_data):
        self.input_data = input_data
    def setLocalFilePath(self,file_path):
        self.file_path = file_path
        self.setLocalInputFile(open(self.file_path))
    def setHDFSFilePath(self,file_path):
        self.file_path = file_path
        self.setInputData(self.sc.textFile(self.file_path,use_unicode=False).cache())


class SubwaySpark(Spark):
    def __init__(self):
        self.subway = Subway()
        self.sorted_record_list = None
        self.user_trip_pair = None
        self.trip_average_time  = None
        self.in_vehicle_time = None
        self.connect()
        self.addExternalFiles()


    def addExternalFiles(self):
        self.sc.addFile("data/shenzhen_subway_station_line.csv")
        self.subway_station_line = SparkFiles.get("shenzhen_subway_station_line.csv")

    def buildRecordList(self):
        '''
        build the record list for each user and sort it by the time
        :return:
        '''
        one_file = self.input_data
        subway_record_list = one_file.map(self.subway.subwayOneRow).filter(lambda x: x is not None)#.map(lambda record: print(record.station_id))
        user_record_list = subway_record_list.map(lambda x: (x.user_id,x)).groupByKey()
        self.sorted_user_record_list = user_record_list.mapValues(list).filter(lambda (k,v): len(v) > 1).map(lambda (k,v): (k, sorted(v, key=lambda record: record.time)))

    def buildDistrictFilter(self,target_district):
        '''
        filter the record station by district
        :return:
        '''
        station_district_mapping = self.sc.textFile("/zf72/data/station_with_region.txt",use_unicode=False).cache()
        station_district_mapping = station_district_mapping.map(self.subway.stationDistrictMappingOneLine).filter(lambda (k,v): v==target_district)
        station_district_mapping = station_district_mapping.map(lambda (k,v): (v,k)).filter(lambda (k,v): '地铁站' in v)
        station_district_mapping = station_district_mapping.map(lambda (k,v): (v.replace('地铁站',''),k))
        self.station_district_mapping = station_district_mapping.reduceByKey(self.subway.removeDuplicateInMapping)

    def buildFilterRecordListByDistrict(self):
        one_file = self.input_data
        subway_record_list = one_file.map(self.subway.subwayOneRow).filter(lambda x: x is not None)#.map(lambda record: print(record.station_id))
        subway_record_list = subway_record_list.map(lambda record: (record.station_name.rstrip('站'),record))
        records_after_filter = subway_record_list.join(self.station_district_mapping).map(lambda (k,v): v[0])
        user_record_list = records_after_filter.map(lambda x: (x.user_id,x)).groupByKey()
        self.sorted_user_record_list = user_record_list.mapValues(list).filter(lambda (k,v): len(v) > 1).map(lambda (k,v): (k, sorted(v, key=lambda record: record.time)))

    def buildTripList(self):
        self.user_trip_pair = self.sorted_user_record_list.map(self.subway.sortedRecordsToTrip).filter(lambda (k,v): len(v)>0)

    def filterTripListByStartDistrict(self):
        user_trip_pair = self.user_trip_pair.flatMap(self.subway.user_trip_to_trip_user)
        user_trip_pair = user_trip_pair.map(lambda (user_id,one_trip): (one_trip.start.station_name.rstrip('站'),(one_trip,user_id)))
        filter_user_trip_pair = user_trip_pair.join(self.station_district_mapping)
        filter_user_trip_pair = filter_user_trip_pair.map(lambda (k,v): (v[0][1],v[0][0])).groupByKey().mapValues(list)
        self.user_trip_pair = filter_user_trip_pair

    

    def filterTripListByDestinationDistrict(self):
        user_trip_pair = self.user_trip_pair.flatMap(self.subway.user_trip_to_trip_user)
        user_trip_pair = user_trip_pair.map(lambda (user_id,one_trip): (one_trip.end.station_name.rstrip('站'),(one_trip,user_id)))
        filter_user_trip_pair = user_trip_pair.join(self.station_district_mapping)
        filter_user_trip_pair = filter_user_trip_pair.map(lambda (k,v): (v[0][1],v[0][0])).groupByKey().mapValues(list)
        self.user_trip_pair = filter_user_trip_pair

    def setStartEndStation(self,start_station=None,end_station=None):
        self.subway.start_station = start_station
        self.subway.end_station = end_station

    def buildNoUserTripList(self):
       self.trip_list =  self.user_trip_pair.flatMap(self.subway.userTripToNoUserTripList)

    def filterTripListByStartEndStation(self,start_station=None,end_station=None):
        self.setStartEndStation(start_station=start_station,end_station=end_station)
        self.filtered_trip_list = self.trip_list.filter(self.subway.filterByStartEndStation)

    def tripStartTimeVsTravelTime(self):
        self.trip_start_time = self.filtered_trip_list.map(lambda trip: (trip.timeSlot(t_min=1),trip.trip_time.total_seconds()))
        return(self.trip_start_time)

    def buildInVehicleTime(self):
        trip_time_pair = self.user_trip_pair.flatMap(self.subway.mapToStationTimeMapping)
        self.in_vehicle_time = trip_time_pair.reduceByKey(self.subway.minimumByKey)
        #self.in_vehicle_time.saveAsTextFile('/zf72/transportation_data/result/in_vehicle_time/0601')

    def buildWaitingTimeInTwoStations(self,start_station=None,end_station=None):
        self.setStartEndStation(start_station,end_station)
        user_trips_in_vehicle_time = self.user_trip_pair.flatMap(self.subway.mapToODTrip).join(self.in_vehicle_time)
        filter_user_trips_in_vehicle_time = user_trips_in_vehicle_time.filter(self.subway.filterWaitingTimeByStartEndStation)
        # for one_record in filter_user_trips_in_vehicle_time.collect():
        #     print(one_record[1][0].start.station_name+","+one_record[1][0].end.station_name)
        self.timeslot_waiting_time = filter_user_trips_in_vehicle_time.map(self.subway.mapToTripWaitingTime).map(lambda (k,v1,v2): (k,v2))
        return(self.timeslot_waiting_time)



    def buildWaitingTime(self,output_file_name):
        #read in_vehicle_time mapping
        user_trips_in_vehicle_time = self.user_trip_pair.flatMap(self.subway.mapToODTrip).join(self.in_vehicle_time)
        timeslot_waiting_time = user_trips_in_vehicle_time.map(self.subway.mapToTripWaitingTime).map(lambda (k,v1,v2): (k,v2))
        self.timeslot_ave_waiting_time = timeslot_waiting_time.combineByKey(
            lambda v: (v,1),
            lambda x,v: (x[0]+v,x[1]+1),
            lambda x,y: (x[0]+y[0],x[1]+y[1])
        ).map(
            lambda (k,v): (k,float(v[0])/float(v[1]))
        )
        self.timeslot_ave_waiting_time.saveAsTextFile("/zf72/transportation_data/result/waiting_time/"+output_file_name)
        # result_json = {}
        # for record in self.timeslot_ave_waiting_time.collect():
        #     result_json[record[0]] = record[1]
        # print(result_json)
        #json.dump(result_json,open('../../data/result/waiting_time.json'))
        # self.user_trip_pair.map(
        #     lambda (k,v):
        # )
        # self.user_trip_pair.join(self.in_vehicle_time)

    def buildTripAveTimeMatrix(self):
        trip_time_pair = self.user_trip_pair.flatMap(self.subway.mapToStationTimeMapping)
        trip_time_count = trip_time_pair.combineByKey(
            lambda v: (v,1),
            lambda x,v: (x[0]+v,x[1]+1),
            lambda x,y: (x[0]+y[0],x[1]+y[1])
        )
        self.trip_average_time = trip_time_count.map(
            lambda (k,v): (k,float(v[0])/float(v[1]))
        )

    def saveAverageTripTime(self,output_file_path,local=False):
        if not local:
            self.trip_average_time.saveAsTextFile(output_file_path)
        else:
            result = self.trip_average_time.collect()
            print(result)

    def filterTripListByWalkingTimeStation(self,target_station):
        self.subway.initWalkingTimeStationLine(self.subway_station_line,target_station)
        #get end station trip
        start_target = self.trip_list.filter(self.subway.routeHandler.filterTripByPreviousStartAndTargetStation)\
            .map(lambda one_trip: ((one_trip.arriveTimeSlot(t_hour=1),one_trip.start.station_name,one_trip.end.station_name),one_trip))\
            .reduceByKey(self.subway.minimumTripByKey).map(lambda (a,b): b).flatMap(self.subway.mapToLineTarget)
        for one_record in start_target.collect():
            print(one_record)
        # #get start station trip
        # target_start = self.trip_list.filter(self.subway.routeHandler.filterTripByTargetStationAndPreviousStation)\
        #     .flatMap(self.subway.mapToLineTarget)
        # #get cross trip
        # target_end = self.trip_list.filter(self.subway.routeHandler.filterTripByTargetStationAndLatterStations)\
        #     .flatMap(self.subway.mapToLineTarget)
        # end_target = self.trip_list.filter(self.subway.routeHandler.filterTripByLatterStationAndTargetStation)\
        #     .flatMap(self.subway.mapToLineTarget)
        # start_end = start_target.join(target_end).union(end_target.join(target_start))
        # start_end_time = start_end.map()
        # two_station_trip_list = self.trip_list.filter(self.subway.routeHandler.filterTripByPreviousLatterSameLine)

    
    def buildWaitingTimeInDistricts(self):
        self.subway.buildStationNameDistrictMapping('/media/zf72/Seagate Backup Plus Drive/E/DATA/edges/subway station/station_with_region.txt')
        #trip_pair = self.user_trip_pair.flatMap(lambda (k,v): (k,v))
        local = self.user_trip_pair.collect()
        for (k,v) in local:
            print (k,v[0].start.district)


class BusSpark(Spark):
    def __init__(self):
        self.bus = Bus()
        self.bus_smart_card_data = None
        self.connect()

    def markSmartCardID(self,output_file_path):
        if self.bus_smart_card_data is None:
            self.filterSmartCardBusData()
        self.mask_bus_smart_card_data = self.bus_smart_card_data.map(self.bus.maskSmartCardID)
        self.mask_bus_smart_card_data.saveAsTextFile(output_file_path)

    def filterSmartCardBusData(self):
        self.bus_smart_card_data = self.input_data.filter(self.bus.filterBusSmartCardData)

class TaxiSpark(Spark):
    def __init__(self):
        self.taxi = Taxi()
        self.connect()
        self.sc.addFile('data/shenzhen_tran_simple_gps.json')
        self.sc.addFile('data/shenzhen_district_simple_gps.json')

    def buildRecordList(self):
       trans_region_file_path = SparkFiles.get("shenzhen_tran_simple_gps.json")
       self.taxi.initPointRegionMapping(trans_region_file_path)
       dist_region_file_path = SparkFiles.get("shenzhen_district_simple_gps.json")
       self.taxi.initPointDistrictMapping(dist_region_file_path)
       self.record_list = self.input_data.map(self.taxi.parseRecord).filter(lambda record: record is not None) #and record.is_occupied)

    def buildTripList(self):
        record_group_user = self.record_list.groupBy(lambda record: record.plate)
        sorted_record_group_user = record_group_user.mapValues(list).map(lambda (k,v): (k, sorted(v, key=lambda record: record.time)))
        self.user_taxi_trip_list = sorted_record_group_user.map(self.taxi.parseRecordTotrip)

    def buildODTravelTime(self):
        self.od_trip_user = self.user_taxi_trip_list.flatMap(self.taxi.userTripToTripUser)
        od_time_mapping = self.od_trip_user.map(lambda (k,v): (k,v[0].trip_time.total_seconds()))
        self.od_minimum_time = od_time_mapping.reduceByKey(min)


    def buildDelayTimeDistribution(self):
        trip_delay_time = self.od_trip_user.join(self.od_minimum_time).map(lambda (k,v): (v[0][0].timeSlot(t_hour=1),k,v[0][0].trip_time.total_seconds()-v[1]))
        delay_time = trip_delay_time.map(lambda (t,l,d):(t,d)).combineByKey(lambda value: (value,1),
                                                                                    lambda x,value: (x[0]+value,x[1]+1),
                                                                                    lambda x,y: (x[0]+y[0],x[1]+y[1]))
        self.average_delay_time =  delay_time.map(lambda (t,(value_sum,count)): (t,float(value_sum)/count))
        return self.average_delay_time

    def setStartFilterDistrictName(self,district_name):
        self.taxi.start_district = district_name
    def setEndFilterDistrictName(self,district_name):
        self.taxi.end_district = district_name

    def filterTripByStartDistrict(self,district_name = None):
        if district_name is not None:
            self.taxi.start_district = district_name
        self.od_trip_user = self.od_trip_user.filter(self.taxi.filterByStartDistrict)

    def filterTripByEndDistrict(self,district_name = None):
        if district_name is not None:
            self.taxi.end_district = district_name
        self.od_trip_user = self.od_trip_user.filter(self.taxi.filterByEndDistrict)


    def test(self):
        # mapping = self.sc.textFile("/zf72/data/edges/shenzhen_tran_simple_gps.json").cache()
        # t = mapping.map(json.loads).collect()
        test = json.load(open('../data/shenzhen_tran_simple_gps.json'))
        print(test.keys())
        

class PVSpark(Spark):
    def __init__(self):
        self.pv  = PV()
        self.connect()
        self.sc.addFile('data/shenzhen_tran_simple_gps.json')
        self.sc.addFile('data/shenzhen_district_simple_gps.json')

    def buildRecordList(self):
        trans_region_file_path = SparkFiles.get("shenzhen_tran_simple_gps.json")
        self.pv.initPointRegionMapping(trans_region_file_path)
        dist_region_file_path = SparkFiles.get("shenzhen_district_simple_gps.json")
        self.pv.initPointDistrictMapping(dist_region_file_path)
        self.record_list = self.input_data.map(self.pv.parseRecord).filter(lambda record: record is not None) #and record.is_occupied)

    def buildTripList(self):
        record_group_user = self.record_list.groupBy(lambda record: record.pv_id)
        sorted_record_group_user = record_group_user.mapValues(list).map(lambda (k,v): (k, sorted(v, key=lambda record: record.time)))
        self.user_taxi_trip_list = sorted_record_group_user.map(self.pv.parseRecordTotrip).filter(lambda (k,v): len(v) > 0)

        for one_record_list in self.user_taxi_trip_list.collect():
            print(one_record_list[0])
            for one_record in one_record_list[1]:
                print(one_record.start.time,one_record.end.time)


    def buildODTravelTime(self):
        self.od_trip_user = self.user_taxi_trip_list.flatMap(self.pv.userTripToTripUser)
        od_time_mapping = self.od_trip_user.map(lambda (k,v): (k,v[0].trip_time.total_seconds()))
        self.od_minimum_time = od_time_mapping.reduceByKey(min)


    def buildDelayTimeDistribution(self):
        trip_delay_time = self.od_trip_user.join(self.od_minimum_time).map(lambda (k,v): (v[0][0].timeSlot(t_hour=1),k,v[0][0].trip_time.total_seconds()-v[1]))
        delay_time = trip_delay_time.map(lambda (t,l,d):(t,d)).combineByKey(lambda value: (value,1),
                                                                                    lambda x,value: (x[0]+value,x[1]+1),
                                                                                    lambda x,y: (x[0]+y[0],x[1]+y[1]))
        self.average_delay_time =  delay_time.map(lambda (t,(value_sum,count)): (t,float(value_sum)/count))
        return self.average_delay_time

    def setStartFilterDistrictName(self,district_name):
        self.pv.start_district = district_name
    def setEndFilterDistrictName(self,district_name):
        self.pv.end_district = district_name

    def filterTripByStartDistrict(self,district_name = None):
        if district_name is not None:
            self.pv.start_district = district_name
        self.od_trip_user = self.od_trip_user.filter(self.pv.filterByStartDistrict)

    def filterTripByEndDistrict(self,district_name = None):
        if district_name is not None:
            self.pv.end_district = district_name
        self.od_trip_user = self.od_trip_user.filter(self.pv.filterByEndDistrict)
