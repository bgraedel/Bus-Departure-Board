from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict
import xml.etree.ElementTree as ET
import pandas as pd
from logging import Logger, getLogger
import zoneinfo
from datetime import timezone, timedelta
import re

from dataclasses import dataclass
from datetime import datetime
import requests
from typing import Optional, List
import xml.etree.ElementTree as ET
from logging import Logger, getLogger
import zoneinfo

@dataclass
class OJPLocationRequestParams:
    """Parameters for location information requests"""
    location_name: str
    max_results: int = 10
    location_type: str = "stop"  # can be 'stop', 'poi', 'address', etc.
    include_pt_modes: bool = False

@dataclass
class Location:
    """Represents a location from the API response"""
    stop_place_ref: Optional[str]
    name: str
    type: str  # 'stop', 'address', 'poi'
    latitude: float
    longitude: float
    parent_ref: Optional[str] = None
    private_code: Optional[str] = None
    topographic_place_ref: Optional[str] = None

class LocationRequestBuilder:
    """Builds XML for location information requests"""
    
    def build_request_xml(self, params: OJPLocationRequestParams) -> str:
        """Build XML for location information request"""
        root = ET.Element("OJP", {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xmlns": "http://www.siri.org.uk/siri",
            "xmlns:ojp": "http://www.vdv.de/ojp",
            "version": "1.0",
            "xsi:schemaLocation": "http://www.siri.org.uk/siri ../ojp-xsd-v1.0/OJP.xsd"
        })

        ojp_request = ET.SubElement(root, "OJPRequest")
        service_request = ET.SubElement(ojp_request, "ServiceRequest")

        # Add timestamp in ISO format with Z
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        ET.SubElement(service_request, "RequestTimestamp").text = now
        ET.SubElement(service_request, "RequestorRef").text = "departure_board"

        location_request = ET.SubElement(service_request, "ojp:OJPLocationInformationRequest")
        ET.SubElement(location_request, "RequestTimestamp").text = now

        # Initial input with location name
        initial_input = ET.SubElement(location_request, "ojp:InitialInput")
        ET.SubElement(initial_input, "ojp:LocationName").text = params.location_name

        # Restrictions
        restrictions = ET.SubElement(location_request, "ojp:Restrictions")
        ET.SubElement(restrictions, "ojp:Type").text = params.location_type
        ET.SubElement(restrictions, "ojp:NumberOfResults").text = str(params.max_results)
        ET.SubElement(restrictions, "ojp:IncludePtModes").text = str(params.include_pt_modes).lower()

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')

class LocationResponseParser:
    """Parser for location information responses"""
    
    NAMESPACES = {
        'siri': 'http://www.siri.org.uk/siri',
        'ojp': 'http://www.vdv.de/ojp'
    }

    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger or getLogger(__name__)

    def _extract_text(self, element: ET.Element, xpath: str) -> Optional[str]:
        """Safely extract text from XML element"""
        if element is None:
            return None
        try:
            text_element = element.find(xpath, self.NAMESPACES)
            return text_element.text if text_element is not None else None
        except AttributeError as e:
            self.logger.debug(f"Failed to extract text from {xpath}", exc_info=e)
            return None

    def parse_xml(self, xml_data: bytes) -> List[Location]:
        """Parse location information response XML"""
        try:
            locations = []
            root = ET.fromstring(xml_data)

            # Check for errors
            if error := root.find(".//ojp:ErrorCondition", self.NAMESPACES):
                raise ValueError(f"API Error: {error.find('ojp:OtherError', self.NAMESPACES).text}")

            # Parse each location
            for loc in root.findall(".//ojp:Location", self.NAMESPACES):
                try:
                    # Get location type and corresponding element
                    stop_place = loc.find("ojp:StopPlace", self.NAMESPACES)
                    stop_point = loc.find("ojp:StopPoint", self.NAMESPACES)
                    address = loc.find("ojp:Address", self.NAMESPACES)
                    poi = loc.find("ojp:PointOfInterest", self.NAMESPACES)

                    # Determine location type and extract data accordingly
                    if stop_place is not None:
                        element = stop_place
                        loc_type = "stop"
                    elif stop_point is not None:
                        element = stop_point
                        loc_type = "stop"
                    elif address is not None:
                        element = address
                        loc_type = "address"
                    elif poi is not None:
                        element = poi
                        loc_type = "poi"
                    else:
                        continue

                    # Extract common fields
                    name = self._extract_text(element, ".//ojp:Text")
                    if not name:
                        continue

                    # Get coordinates
                    geo_pos = loc.find("ojp:GeoPosition", self.NAMESPACES)
                    if geo_pos is not None:
                        lat = float(self._extract_text(geo_pos, "siri:Latitude") or 0)
                        lon = float(self._extract_text(geo_pos, "siri:Longitude") or 0)
                    else:
                        lat = lon = 0.0

                    # Create location object
                    location = Location(
                        stop_place_ref=self._extract_text(element, "ojp:StopPlaceRef"),
                        name=name,
                        type=loc_type,
                        latitude=lat,
                        longitude=lon,
                        parent_ref=self._extract_text(element, "ojp:ParentRef"),
                        private_code=self._extract_text(element, "ojp:PrivateCode/ojp:Value"),
                        topographic_place_ref=self._extract_text(element, "ojp:TopographicPlaceRef")
                    )
                    locations.append(location)

                except Exception as e:
                    self.logger.error(f"Failed to parse location element", exc_info=e)
                    continue

            return locations

        except ET.ParseError as e:
            self.logger.error("Failed to parse XML", exc_info=e)
            raise

@dataclass
class OJPRequestParams:
    """Updated parameters with operator filtering"""
    stop_place_ref: str
    location_name: str
    request_type: str = "departure"
    max_results: Optional[int] = None
    operator_ref: Optional[str] = None
    exclude_operator: bool = False
    include_previous_calls: bool = True
    include_onward_calls: bool = True
    include_realtime: bool = True
    departure_time: Optional[datetime] = None

class OJPClient:
    def __init__(self, 
                 base_url: str,
                 api_key: Optional[str] = None,
                 timeout: int = 30,
                 timezone: str = 'Europe/Zurich',
                 logger: Optional[Logger] = None):
        """Initialize OJP client"""
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.timezone = zoneinfo.ZoneInfo(timezone)
        self.logger = logger or getLogger(__name__)

    def _build_request_xml(self, params: OJPRequestParams) -> str:
        """Build XML matching the latest example structure"""
        root = ET.Element("OJP", {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xmlns": "http://www.siri.org.uk/siri",
            "xmlns:ojp": "http://www.vdv.de/ojp",
            "version": "1.0",
            "xsi:schemaLocation": "http://www.siri.org.uk/siri ../ojp-xsd-v1.0/OJP.xsd"
        })

        ojp_request = ET.SubElement(root, "OJPRequest")
        service_request = ET.SubElement(ojp_request, "ServiceRequest")

        # Timestamp with milliseconds
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        ET.SubElement(service_request, "RequestTimestamp").text = now
        ET.SubElement(service_request, "RequestorRef").text = "API-Explorer"

        stop_event = ET.SubElement(service_request, "ojp:OJPStopEventRequest")
        ET.SubElement(stop_event, "RequestTimestamp").text = now

        # Location section
        location = ET.SubElement(stop_event, "ojp:Location")
        place_ref = ET.SubElement(location, "ojp:PlaceRef")
        
        # Critical: No namespace prefix for StopPlaceRef
        ET.SubElement(place_ref, "StopPlaceRef").text = params.stop_place_ref
        
        loc_name = ET.SubElement(place_ref, "ojp:LocationName")
        ET.SubElement(loc_name, "ojp:Text").text = params.location_name

        # Optional DepArrTime
        if params.departure_time:
            dep_time = params.departure_time.strftime("%Y-%m-%dT%H:%M:%S")
            ET.SubElement(location, "ojp:DepArrTime").text = dep_time

        # Parameters section
        params_elem = ET.SubElement(stop_event, "ojp:Params")

        # Operator filter if provided
        if params.operator_ref:
            operator_filter = ET.SubElement(params_elem, "ojp:OperatorFilter")
            ET.SubElement(operator_filter, "ojp:Exclude").text = str(params.exclude_operator).lower()
            ET.SubElement(operator_filter, "ojp:OperatorRef").text = params.operator_ref

        # Main parameters
        ET.SubElement(params_elem, "ojp:StopEventType").text = params.request_type
        
        if params.max_results:
            ET.SubElement(params_elem, "ojp:NumberOfResults").text = str(params.max_results)
        
        ET.SubElement(params_elem, "ojp:IncludePreviousCalls").text = str(params.include_previous_calls).lower()
        ET.SubElement(params_elem, "ojp:IncludeOnwardCalls").text = str(params.include_onward_calls).lower()
        ET.SubElement(params_elem, "ojp:IncludeRealtimeData").text = str(params.include_realtime).lower()

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')

    def send_stop_request(self, params: OJPRequestParams) -> str:
        """Make request to OJP API for stop events"""
        headers = {
            'Content-Type': 'application/xml',
        }
        
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        xml_request = self._build_request_xml(params)

        encoded_request = xml_request.encode('UTF-8')

        self.logger.debug(f"Request XML:\n{xml_request}")
        response = requests.post(
            self.base_url,
            data=encoded_request,
            headers=headers,
            timeout=self.timeout
        )
        
        response.raise_for_status()
        return response.content
    
    def send_location_request(self, params: OJPLocationRequestParams) -> str:
        """Send location information request to OJP API"""
        builder = LocationRequestBuilder()
        xml_request = builder.build_request_xml(params)
        
        headers = {
            'Content-Type': 'application/xml',
        }
        
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        encoded_request = xml_request.encode('UTF-8')
        
        self.logger.debug(f"Location Request XML:\n{xml_request}")
        response = requests.post(
            self.base_url,
            data=encoded_request,
            headers=headers,
            timeout=self.timeout
        )
        
        response.raise_for_status()
        return response.content

@dataclass
class Stop:
    """Represents a transit stop with arrival/departure times"""
    name: str
    platform: Optional[str]
    timetabled_arrival: Optional[datetime]
    estimated_arrival: Optional[datetime]
    timetabled_departure: Optional[datetime]
    estimated_departure: Optional[datetime]

@dataclass
class TransitTrip:
    """Represents a single transit trip with its stops"""
    line: str
    mode: str
    current_stop: Stop
    destination: str
    future_stops: List[Stop]
    operator_ref: Optional[str]
    operator_name: Optional[str]
    journey_ref: Optional[str]
    line_ref: Optional[str] = None  # Line identifier from LineRef
    direction_ref: Optional[str] = None  # Direction identifier
    direction_name: Optional[str] = None  # Published direction name
    cancelled: Optional[str] = None  # 'true' if trip is cancelled

class TransitXMLParser:
    """Parser for SIRI/OJP transit XML responses"""
    
    NAMESPACES = {
        'siri': 'http://www.siri.org.uk/siri',
        'ojp': 'http://www.vdv.de/ojp'
    }

    def __init__(self, 
                 default_timezone: str = 'Europe/Zurich',
                 target_timezone: Optional[str] = None,
                 logger: Optional[Logger] = None):
        """
        Initialize the parser with timezone settings
        
        Args:
            default_timezone: Default timezone for times without explicit zone
            target_timezone: Timezone to convert all times to (if None, keeps original)
            logger: Optional logger instance 
        """
        self.logger = logger or getLogger(__name__)
        try:
            self.default_timezone = zoneinfo.ZoneInfo(default_timezone)
            self.target_timezone = (zoneinfo.ZoneInfo(target_timezone) 
                                  if target_timezone else None)
        except zoneinfo.ZoneInfoNotFoundError as e:
            self.logger.error(f"Invalid timezone specified: {e}")
            raise ValueError(f"Invalid timezone: {e}")

    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """
        Convert datetime string to datetime object with proper timezone handling
        
        Handles formats:
        - ISO 8601 with Z (UTC)
        - ISO 8601 with offset (+01:00)
        - ISO 8601 without timezone
        """
        if not dt_str:
            return None
        
        try:
            # Remove any microseconds for consistency
            dt_str = re.sub(r'\.\d+', '', dt_str)
            
            # Handle UTC marker
            if dt_str.endswith('Z'):
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            else:
                # Check if string has timezone offset
                if '+' in dt_str or '-' in dt_str:
                    dt = datetime.fromisoformat(dt_str)
                else:
                    # No timezone specified, use default
                    dt = datetime.fromisoformat(dt_str).replace(tzinfo=self.default_timezone)
            
            # Convert to target timezone if specified
            if self.target_timezone:
                dt = dt.astimezone(self.target_timezone)
                
            return dt

        except ValueError as e:
            self.logger.warning(f"Failed to parse datetime: {dt_str}", exc_info=e)
            return None

    def _extract_text(self, element: Optional[ET.Element], xpath: str) -> Optional[str]:
        """Safely extract text from an XML element using XPath"""
        if element is None:
            return None
        try:
            text_element = element.find(xpath, self.NAMESPACES)
            return text_element.text if text_element is not None else None
        except AttributeError as e:
            self.logger.debug(f"Failed to extract text from {xpath}", exc_info=e)
            return None

    def _parse_stop(self, stop_element: ET.Element) -> Optional[Stop]:
        """Parse a stop element into a Stop object"""
        try:
            name = self._extract_text(stop_element, "ojp:StopPointName/ojp:Text")
            if not name:
                return None

            platform = self._extract_text(stop_element, "ojp:PlannedQuay/ojp:Text")
            
            # Parse arrival times if present
            arr_element = stop_element.find("ojp:ServiceArrival", self.NAMESPACES)
            tt_arr = self._parse_datetime(self._extract_text(arr_element, "ojp:TimetabledTime"))
            est_arr = self._parse_datetime(self._extract_text(arr_element, "ojp:EstimatedTime"))
            
            # Parse departure times if present
            dep_element = stop_element.find("ojp:ServiceDeparture", self.NAMESPACES)
            tt_dep = self._parse_datetime(self._extract_text(dep_element, "ojp:TimetabledTime"))
            est_dep = self._parse_datetime(self._extract_text(dep_element, "ojp:EstimatedTime"))

            return Stop(
                name=name,
                platform=platform,
                timetabled_arrival=tt_arr,
                estimated_arrival=est_arr,
                timetabled_departure=tt_dep,
                estimated_departure=est_dep
            )
        except Exception as e:
            self.logger.error(f"Failed to parse stop element", exc_info=e)
            return None

    def parse_xml(self, xml_data: bytes) -> List[TransitTrip]:
        try:
            trips = []
            root = ET.fromstring(xml_data)
            if error := root.find(".//ojp:ErrorCondition", self.NAMESPACES):
                raise ValueError(f"API Error: {error.find('ojp:OtherError', self.NAMESPACES).text}")

            for stop_event in root.findall(".//ojp:StopEvent", self.NAMESPACES):
                try:
                    service = stop_event.find("ojp:Service", self.NAMESPACES)
                    extension = stop_event.find("ojp:Extension", self.NAMESPACES)
                    if service is None:
                        continue

                    # Extract line information
                    line_ref = self._extract_text(service, "siri:LineRef")
                    line_name = self._extract_text(service, "ojp:PublishedLineName/ojp:Text")
                    line = line_name if line_name else line_ref  # Fallback to LineRef if name missing

                    # Extract direction information
                    direction_ref = self._extract_text(service, "siri:DirectionRef")
                    mode = self._extract_text(service, "ojp:Mode/ojp:PtMode")
                    destination = self._extract_text(service, "ojp:DestinationText/ojp:Text")
                    operator_ref = self._extract_text(service, "ojp:OperatorRef")
                    operator_name = self._extract_text(extension, "ojp:OperatorName/ojp:Text")
                    journey_ref = self._extract_text(service, "ojp:JourneyRef")
                    cancelled = self._extract_text(service, "ojp:Cancelled")

                    if not all([line, mode, destination]):
                        self.logger.warning("Missing required trip information")
                        continue

                    # Parse current stop
                    this_call = stop_event.find("ojp:ThisCall/ojp:CallAtStop", self.NAMESPACES)
                    if this_call is None:
                        continue
                        
                    current_stop = self._parse_stop(this_call)
                    if current_stop is None:
                        continue

                    # Parse future stops
                    future_stops = []
                    for onward in stop_event.findall("ojp:OnwardCall/ojp:CallAtStop", self.NAMESPACES):
                        if stop := self._parse_stop(onward):
                            future_stops.append(stop)

                    trips.append(TransitTrip(
                        line=line,
                        line_ref=line_ref,
                        mode=mode,
                        current_stop=current_stop,
                        destination=destination,
                        future_stops=future_stops,
                        operator_name=operator_name,
                        operator_ref=operator_ref,
                        journey_ref=journey_ref,
                        direction_ref=direction_ref,
                        cancelled=cancelled,
                    ))

                except ET.ParseError as e:
                    self.logger.error("Invalid XML", exc_info=True)
                    raise

            return trips

        except ET.ParseError as e:
            self.logger.error("Failed to parse XML", exc_info=e)
            raise

    def to_dataframe(self, 
                    trips: List[TransitTrip], 
                    time_format: Optional[str] = None) -> pd.DataFrame:
        """
        Convert trips to a pandas DataFrame
        
        Args:
            trips: List of TransitTrip objects
            time_format: Optional format string for datetime columns (e.g., '%H:%M')
        """
        records = []
        for trip in trips:
            records.append({
                'line': trip.line,
                'line_ref': trip.line_ref,
                'direction_ref': trip.direction_ref,
                'mode': trip.mode,
                'current_stop': trip.current_stop.name,
                'platform': trip.current_stop.platform,
                'timetabled_departure': trip.current_stop.timetabled_departure,
                'estimated_departure': trip.current_stop.estimated_departure,
                'destination': trip.destination,
                'operator_ref': trip.operator_ref,
                'operator_name': trip.operator_name,
                'journey_ref': trip.journey_ref,
                'future_stops': [stop.name for stop in trip.future_stops]
            })
            
        # Sort records by:
        #   - estimated_departure if it's not None
        #   - otherwise fall back to timetabled_departure
        records.sort(key=lambda r: r['estimated_departure'] or r['timetabled_departure'])
        
        # Create the DataFrame
        df = pd.DataFrame(records)

        # Finally, format times if requested (do this after sorting so they remain datetimes during sorting)
        if time_format:
            for col in ['timetabled_departure', 'estimated_departure']:
                df[col] = df[col].apply(lambda x: x.strftime(time_format) if x else None)
        
        return df


def filter_trips_by_station(trips: List[TransitTrip], station_keyword: str, max_length: Optional[int]) -> List[TransitTrip]:
    """Filter trips that pass through a specific station"""
    keyword = station_keyword.lower()
    filtered_trips = [
        trip for trip in trips
        if (keyword in trip.current_stop.name.lower() or
            any(keyword in stop.name.lower() for stop in trip.future_stops))
    ]
    # sort by estimated departure time if available or fallback to timetabled departure
    filtered_trips.sort(key=lambda t: t.current_stop.estimated_departure or t.current_stop.timetabled_departure)
    # print service, destination and departure time
    for trip in filtered_trips:
        print(f"{trip.line} to {trip.destination} at {trip.current_stop.estimated_departure or trip.current_stop.timetabled_departure}")
    return filtered_trips[:max_length] if max_length else filtered_trips


def fetch_locations(client, parser, stop_names):
    locations = []
    for stop in stop_names:
        print(f"Fetching location for {stop}")
        location_params = OJPLocationRequestParams(
            location_name=stop,
            max_results=1,
            location_type="stop",
        )
        response = client.send_location_request(location_params)
        parsed_locations = parser.parse_xml(response)
        if parsed_locations:
            locations.append(parsed_locations[0])
    return locations


def main():
    import os
    from logging import StreamHandler

    # Initialize client
    client = OJPClient(
        base_url="https://api.opentransportdata.swiss/ojp2020",
        api_key=os.environ.get("OJP_API_KEY"),
        timezone="Europe/Zurich",
    )

    tz = zoneinfo.ZoneInfo('Europe/Zurich')



    # Create location request parameters
    location_params = OJPLocationRequestParams(
        location_name="Bern, Bahnhof",	
        max_results=10,
        location_type="stop",
    )

    # Send request
    response = client.send_location_request(location_params)

    # Parse response
    parser = LocationResponseParser()
    locations = parser.parse_xml(response)

    # Create request parameters
    params = OJPRequestParams(
        stop_place_ref=locations[0].stop_place_ref,
        location_name=locations[0].name,
        departure_time=datetime.now(tz) - timedelta(minutes=480),
        max_results=20,  # Limit to 10 results
    )

    # Make request
    response = client.send_stop_request(params)

    parser = TransitXMLParser(
        default_timezone='UTC',  # Times without timezone will be assumed to be Swiss time
        target_timezone='Europe/Zurich'    # Keep everything in Swiss time
    )

    # Parse XML
    trips = parser.parse_xml(response)

    # Filter trips by station
    trips = filter_trips_by_station(trips, "Bern, Bahnhof", max_length=5)

    # Convert to DataFrame with formatted times
    df = parser.to_dataframe(trips, time_format='%Y-%m-%d %H:%M:%S')  # Show only hours and minutes

    print(df)

if __name__ == '__main__':
    main()
