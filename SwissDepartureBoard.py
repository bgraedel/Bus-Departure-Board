# This software was produced by Jonathan Foot (c) 2023, all rights reserved.
# Project Website : https://departureboard.jonathanfoot.com
# Documentation   : https://jonathanfoot.com/Projects/DepartureBoard
# Description	 : This program allows you to display a live bus departure board for any UK bus stop nationally.
# Python 3 Required.

import time
import inspect, os
import sys
import json
import argparse
from urllib.request import urlopen
from PIL import ImageFont, Image, ImageDraw
from luma.core.render import canvas
from luma.core import cmdline
from datetime import datetime
from luma.core.image_composition import ImageComposition, ComposableImage
from ojp_v1_departure_parser import (
    OJPClient,
    TransitXMLParser,
    filter_trips_by_station,
    OJPRequestParams,
    LocationResponseParser,
    TransitTrip,
    fetch_locations,
)
import zoneinfo
import threading
from config import STOP_NAMES

# Used to get live data from the Transport API and represent a specific services and it's details.
import asyncio
from datetime import datetime
import zoneinfo


###
# Below Declares all the program optional and compulsory settings/ start up paramters.
###
## Start Up Paramarter Checks
# Checks value is greater than Zero.
def check_positive(value):
    try:
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError(
                "%s is invalid, value must be an integer value greater than 0." % value
            )
        return ivalue
    except:
        raise argparse.ArgumentTypeError(
            "%s is invalid, value must be an integer value greater than 0." % value
        )


# Checks string is a valid time range, in the format of "00:00-24:00"
def check_time(value):
    try:
        datetime.strptime(value.split("-")[0], "%H:%M").time()
        datetime.strptime(value.split("-")[1], "%H:%M").time()
    except:
        raise argparse.ArgumentTypeError(
            "%s is invalid, value must be in the form of XX:XX-YY:YY, where the values are in 24hr format."
            % value
        )
    return [
        datetime.strptime(value.split("-")[0], "%H:%M").time(),
        datetime.strptime(value.split("-")[1], "%H:%M").time(),
    ]


## Defines all optional paramaters
parser = argparse.ArgumentParser(
    description="National Buses Live Departure Board, to run the program you will need to pass it all of the required paramters and you may wish to pass any optional paramters."
)
parser.add_argument(
    "-t",
    "--TimeFormat",
    help="Do you wish to use 24hr or 12hr time format; default is 24hr.",
    type=int,
    choices=[12, 24],
    default=24,
)
parser.add_argument(
    "-v",
    "--Speed",
    help="What speed do you want the text to scroll at on the display; default is 3, must be greater than 0.",
    type=check_positive,
    default=3,
)
parser.add_argument(
    "-d",
    "--Delay",
    help="How long the display will pause before starting the next animation; default is 30, must be greater than 0.",
    type=check_positive,
    default=30,
)
parser.add_argument(
    "-r",
    "--RecoveryTime",
    help="How long the display will wait before attempting to get new data again after previously failing; default is 100, must be greater than 0.",
    type=check_positive,
    default=100,
)
parser.add_argument(
    "-y",
    "--Rotation",
    help="Defines which way up the screen is rendered; default is 0",
    type=int,
    default=0,
    choices=[0, 2],
)
parser.add_argument(
    "-l",
    "--RequestLimit",
    help="Defines the minium amount of time the display must wait before making a new data request; default is 75(seconds)",
    type=check_positive,
    default=15,
)
parser.add_argument(
    "-z",
    "--StaticUpdateLimit",
    help="Defines the amount of time the display will wait before updating the expected arrival time (based upon it's last known predicted arrival time); default is  15(seconds), this should be lower than your 'RequestLimit'",
    type=check_positive,
    default=5,
)
parser.add_argument(
    "-e",
    "--EnergySaverMode",
    help="To save screen from burn in and prolong it's life it is recommend to have energy saving mode enabled. 'off' is default, between the hours set the screen will turn off. 'dim' will turn the screen brightness down, but not completely off. 'none' will do nothing and leave the screen on; this is not recommend, you can change your active hours instead.",
    type=str,
    choices=["none", "dim", "off"],
    default="dim",
)
parser.add_argument(
    "-i",
    "--InactiveHours",
    help="The period of time for which the display will go into 'Energy Saving Mode' if turned on; default is '23:00-07:00'",
    type=check_time,
    default="23:00-07:00",
)
parser.add_argument(
    "-o",
    "--Destination",
    choices=["1", "2"],
    default="1",
    help="Depending on the region the buses destination reported maybe a generic place holder location. If this is the case you can switch to mode 2 for the last stop name.",
)
parser.add_argument(
    "-f",
    "--FixedLocations",
    type=check_positive,
    default=3,
    help="If you are using 'fixed' via message this value will limit the max number of via destinations. Taking F locations evenly between a route.",
)
parser.add_argument(
    "--ExtraLargeLineName",
    dest="LargeLineName",
    action="store_true",
    help="By default the service number/ name assumes it will be under 3 characters in length ie 0 - 999. Some regions may use words, such as 'Indigo' Service in Nottingham. Use this tag to expand the named region. When this is on you can not also have show index turned on.",
)
parser.add_argument(
    "--ReducedAnimations",
    help="If you wish to stop the Via animation and cycle faster through the services use this tag to turn the animation off.",
    dest="ReducedAnimations",
    action="store_true",
)
parser.add_argument(
    "--UnfixNextToArrive",
    dest="FixToArrive",
    action="store_false",
    help="Keep the bus sonnest to next arrive at the very top of the display until it has left; by default true",
)
parser.add_argument(
    "--no-splashscreen",
    dest="SplashScreen",
    action="store_false",
    help="Do you wish to see the splash screen at start up; recommended and on by default.",
)
parser.add_argument(
    "--ShowIndex",
    dest="ShowIndex",
    action="store_true",
    help="Do you wish to see index position for each service due to arrive. This can not be turned on with 'ExtraLargeLineName'",
)
parser.add_argument(
    "--Display",
    default="ssd1322",
    choices=["ssd1322", "pygame", "capture", "gifanim"],
    help="Used for development purposes, allows you to switch from a physical display to a virtual emulated one; default 'ssd1322'",
)
parser.add_argument(
    "--max-frames",
    default=60,
    dest="maxframes",
    type=check_positive,
    help="Used only when using gifanim emulator, sets how long the gif should be.",
)
parser.add_argument(
    "--filename",
    dest="filename",
    default="output.gif",
    help="Used mainly for development, if using a gifanim display, this can be used to set the output gif file name, this should always end in .gif.",
)

Args = parser.parse_args()

## Defines all the programs "global" variables
# Defines the fonts used throughout most the program
BasicFontHeight = 14
BasicFont = ImageFont.truetype(
    "%s/resources/lower.ttf"
    % (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))),
    BasicFontHeight,
)
SmallFont = ImageFont.truetype(
    "%s/resources/lower.ttf"
    % (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))),
    12,
)

if Args.LargeLineName and Args.ShowIndex:
    print(
        "You can not have both '--ExtraLargeLineName' and '--ShowIndex' turned on at the same time."
    )
    sys.exit()

if Args.LargeLineName and Args.ShowIndex:
    print(
        "You can not have both '--ExtraLargeLineName' and '--ShowIndex' turned on at the same time."
    )
    sys.exit()

client = OJPClient(
    base_url="https://api.opentransportdata.swiss/ojp2020",
    api_key=os.environ.get("OJP_API_KEY"),
    timezone="Europe/Zurich",
)

# Fetch locations
LOCATIONS = fetch_locations(client, LocationResponseParser(), STOP_NAMES)


###
# Below contains the class which is used to reperesent one instance of a service record. It is also responsible for getting the information from the Transport API.
###
# Used to create a blank object, needed in start-up or when there are less than 3 services currently scheduled.
class LiveTimeStud:
    def __init__(self):
        self.ServiceNumber = " "
        self.Destination = " "
        self.DisplayTime = " "
        self.SchArrival = " "
        self.ExptArrival = " "
        self.Via = " "
        self.ID = "0"

    def TimePassedStatic(self):
        return False


class LiveTime:
    # The last time an API call was made to get new data.
    LastUpdate = datetime.now()

    def __init__(self, Data: TransitTrip, Index):
        self.ID = str(Data.journey_ref)
        self.Operator = str(Data.operator_name)
        self.ServiceNumber = str(Data.line)
        self.Destination = str(Data.destination)
        self.Cancelled = Data.cancelled
        self.SchArrival = Data.current_stop.timetabled_departure
        self.ExptArrival = (
            Data.current_stop.estimated_departure
            if Data.current_stop.estimated_departure is not None
            else Data.current_stop.timetabled_departure
        )

        # The "Via" message, which lists where the service will go through, if unknown use generic message.
        self.Via = ", ".join(
            [stop.name.replace("Bern, ", "") for stop in Data.future_stops]
        )

        # The formatted string containing the time of arrival, to be printed on the display screen.
        self.DisplayTime = self.GetDisplayTime()

    def GetDisplayTime(self):
        # Last time the display screen was updated to reflect the new time of arrival.
        tz = zoneinfo.ZoneInfo("Europe/Zurich")
        self.LastStaticUpdate = datetime.now()

        Arrival = self.ExptArrival
        # The difference between the time now and when it is predicted to arrive.
        Diff = (Arrival - datetime.now(tz)).total_seconds() / 60
        if Diff <= 1 and Diff > 0.1:
            return "<Bus>"
        if Diff <= 0.1:
            return "<Bus> blinking"
        if Diff >= 15:
            return " " + Arrival.time().strftime(
                "%H:%M" if (Args.TimeFormat == 24) else "%I:%M"
            )
        if Diff > 1 and Diff < 10:
            minutes = int(Diff)
            seconds = int((Diff - minutes) * 60)
            # Round seconds down to the nearest 10 for a simpler countdown
            seconds = (seconds // 10) * 10
            return f"{minutes}'{str(seconds).zfill(2)}"
        return f"{Diff:.0f}'"

    # Returns True/False if enough time passed since last update (to avoid API spam).
    @staticmethod
    def TimePassed():
        return (
            datetime.now() - LiveTime.LastUpdate
        ).total_seconds() > Args.RequestLimit

    # Returns True/False if enough time passed since last static update to re-draw display time
    def TimePassedStatic(self):
        """
        Returns True if enough time has passed since the last update
        that we should refresh this service row.
        Special case: If self.DisplayTime contains '<Bus> blinking',
        we refresh once every 0.5 seconds to achieve a consistent blink.
        """
        elapsed = (datetime.now() - self.LastStaticUpdate).total_seconds()

        # If we are blinking, refresh each half-second (tweak to taste)
        if "<Bus> blinking" in self.DisplayTime:
            return elapsed > 0.5

        # Otherwise, refresh only if we see certain keywords AND
        # enough time has passed since last update.
        return (
            any(keyword in self.DisplayTime for keyword in ["min", "<Bus>", "'"])
            and elapsed > Args.StaticUpdateLimit
        )

    #
    # === Old synchronous code, extracted into _fetch_data_sync() ===
    #
    @staticmethod
    def _fetch_data_sync():
        """
        Performs the same blocking HTTP request + parsing
        that used to be in GetData().
        """
        LiveTime.LastUpdate = datetime.now()
        services = []

        tz = zoneinfo.ZoneInfo("Europe/Zurich")
        parser = TransitXMLParser(
            default_timezone="UTC",  # Times without timezone will be assumed to be Swiss time
            target_timezone="Europe/Zurich",  # Keep everything in Swiss time
        )

        all_trips = []
        for location in LOCATIONS:
            # Create request parameters
            params = OJPRequestParams(
                stop_place_ref=location.stop_place_ref,
                location_name=location.name,
                departure_time=datetime.now(tz),  # Departure time is now
                max_results=10,  # Limit to 10 results
            )

            response = client.send_stop_request(params)
            # Parse XML
            trips = parser.parse_xml(response)
            # Filter trips by station
            for trip in trips:
                all_trips.append(trip)

        all_trips = filter_trips_by_station(all_trips, "Bern, Bahnhof", 5)

        for i, trip in enumerate(all_trips):
            if trip.cancelled:
                continue
            print(
                trip.current_stop.name,
                trip.current_stop.estimated_departure,
                trip.line,
                trip.destination,
            )
            services.append(LiveTime(trip, i))
        print("New Data fetched at ", datetime.now())

        return services

    #
    # === Public async method to fetch data, calls _fetch_data_sync() in a thread ===
    #
    @staticmethod
    async def GetDataAsync():
        """
        Asynchronously fetch live data by running _fetch_data_sync()
        on a worker thread. This avoids blocking the event loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, LiveTime._fetch_data_sync)


###
# Below contains everything for the drawing on the board.
# All text must be converted into Images, for the image to be displayed on the display.
###


# Used to create the time on the board or any other basic text box.
class TextImage:
    def __init__(self, device, text):
        self.device = device
        self.text = text
        self.ImageBus = Image.open("bus.png").resize((16, 16))
        self.ImageBlank = Image.new(device.mode, (16, 16), (0, 0, 0))
        self.image = None
        self.width = 0
        self.height = 0
        self.update()  # Initial draw

    def update(self):
        self.image = Image.new(self.device.mode, (self.device.width, 16), (0, 0, 0))
        draw = ImageDraw.Draw(self.image)

        if self.text == "<Bus>":
            self.image.paste(self.ImageBus, (0, 0))
            self.width = 16
            self.height = 16
        elif self.text == "<Bus> blinking":
            # Use the global blink state
            if BlinkState.is_visible():
                self.image.paste(self.ImageBus, (0, 0))
            else:
                self.image.paste(self.ImageBlank, (0, 0))
            self.width = 16
            self.height = 16
        else:
            draw.text((0, 0), self.text, font=BasicFont, fill="white")
            self.width = 5 + int(draw.textlength(self.text, BasicFont))
            self.height = 5 + BasicFontHeight
        del draw


# Used to create the Service number text box, due to needing to adjust font size dynamically.
class TextImageServiceNumber:
    def __init__(self, device, text):
        self.image = Image.new(device.mode, (device.width, 16))
        draw = ImageDraw.Draw(self.image)
        draw.text(
            (0, 0), text, font=BasicFont if len(text) <= 3 else SmallFont, fill="white"
        )

        self.width = 5 + int(draw.textlength(text, BasicFont))
        self.height = 5 + BasicFontHeight
        del draw


# Used to create the destination and via board.
class TextImageComplex:
    def __init__(self, device, destination, via, startOffset):
        self.image = Image.new(device.mode, (device.width * 20, 16))
        draw = ImageDraw.Draw(self.image)
        draw.text((0, 0), destination, font=BasicFont, fill="white")
        draw.text(
            (
                max(
                    (device.width - startOffset),
                    int(draw.textlength(destination, font=BasicFont)) + 6,
                ),
                0,
            ),
            via,
            font=BasicFont,
            fill="white",
        )

        self.width = device.width + int(draw.textlength(via, BasicFont)) - startOffset
        self.height = 16
        del draw


# Used for the opening animation, creates a static two lines of the new and previous service.
class StaticTextImage:
    def __init__(self, device, service, previous_service):
        self.image = Image.new(device.mode, (device.width, 32))
        draw = ImageDraw.Draw(self.image)

        # Prepare the time strings as images
        displayTimeTempPrevious = TextImage(device, previous_service.DisplayTime)
        displayTimeTemp = TextImage(device, service.DisplayTime)

        # --- Draw the *new* service (on the lower half: y=16) ---
        if service.ServiceNumber in ["<Bus>", "<Bus> blinking"]:
            # Draw bus icon
            bus_img = Image.open("bus.png").resize((16, 16))
            # (x=0, y=16) is where you used to draw text for the new service number
            self.image.paste(bus_img, (0, 16), bus_img)
        else:
            # Draw regular text
            draw.text(
                (0, 16),
                service.ServiceNumber,
                font=BasicFont if len(service.ServiceNumber) <= 3 else SmallFont,
                fill="white",
            )

        # Display time for new service
        self.image.paste(
            displayTimeTemp.image, (device.width - displayTimeTemp.width, 16)
        )

        # Destination for new service
        draw.text(
            (45 if Args.ShowIndex or Args.LargeLineName else 30, 16),
            service.Destination,
            font=BasicFont,
            fill="white",
        )

        # --- Draw the *previous* service (on the upper half: y=0) ---
        if previous_service.ServiceNumber in ["<Bus>", "<Bus> blinking"]:
            bus_img_prev = Image.open("icons8-bus-48.png").resize((10, 10))
            self.image.paste(bus_img_prev, (0, 0), bus_img_prev)
        else:
            draw.text(
                (0, 0),
                previous_service.ServiceNumber,
                font=(
                    BasicFont if len(previous_service.ServiceNumber) <= 3 else SmallFont
                ),
                fill="white",
            )

        # Display time for previous service
        self.image.paste(
            displayTimeTempPrevious.image,
            (device.width - displayTimeTempPrevious.width, 0),
        )

        # Destination for previous service
        draw.text(
            (45 if Args.ShowIndex or Args.LargeLineName else 30, 0),
            previous_service.Destination,
            font=BasicFont,
            fill="white",
        )

        self.width = device.width
        self.height = 32

        del draw


# Used to draw a black cover over hidden stuff.
class RectangleCover:
    def __init__(self, device):
        w = device.width
        h = 16

        self.image = Image.new(device.mode, (w, h))
        draw = ImageDraw.Draw(self.image)
        draw.rectangle((0, 0, device.width, 16), outline="black", fill="black")

        del draw
        self.width = w
        self.height = h


# Error message displayed when no data can be found.
class NoService:
    def __init__(self, device):
        w = device.width
        h = 16
        msg = "No Scheduled Services Found"
        self.image = Image.new(device.mode, (w, h))
        draw = ImageDraw.Draw(self.image)
        draw.text((0, 0), msg, font=BasicFont, fill="white")

        self.width = int(draw.textlength(msg, font=BasicFont))
        self.height = h
        del draw


###
## Synchronizer, used to keep track what is busy doing work and what is ready to do more work.
###


# Used to ensure that only 1 animation is playing at any given time, apart from at the start; where all three can animate in.
class Synchroniser:
    def __init__(self):
        self.synchronised = {}

    def busy(self, task):
        self.synchronised[id(task)] = False

    def ready(self, task):
        self.synchronised[id(task)] = True

    def is_synchronised(self):
        for task in self.synchronised.items():
            if task[1] == False:
                return False
        return True


class BlinkState:
    """
    A class that toggles its internal blink state every X seconds in a background thread.
    Now with thread safety.
    """

    _blink_visible = False
    _interval = 1.0
    _stop_event = threading.Event()
    _lock = threading.Lock()  # Add a lock for thread safety

    @classmethod
    def start(cls, interval: float = 1.0):
        """
        Begin blinking in the background, toggling every 'interval' seconds.
        """
        cls._interval = interval
        # Make sure the stop event isn't set from any previous run
        cls._stop_event.clear()
        # Start background thread
        thread = threading.Thread(target=cls._run, daemon=True)
        thread.start()

    @classmethod
    def _run(cls):
        """
        The worker method that runs in the background, flipping _blink_visible.
        Now thread-safe.
        """
        while not cls._stop_event.is_set():
            time.sleep(cls._interval)
            with cls._lock:
                cls._blink_visible = not cls._blink_visible

    @classmethod
    def is_visible(cls) -> bool:
        """
        Returns whether the blink state is currently "visible".
        Now thread-safe.
        """
        with cls._lock:
            return cls._blink_visible

    @classmethod
    def stop(cls):
        """
        Stop the blink thread (for cleanup).
        """
        cls._stop_event.set()


class ScrollTime:
    WAIT_OPENING = 0
    OPENING_SCROLL = 1
    OPENING_END = 2
    SCROLL_DECIDER = 3
    SCROLLING_WAIT = 4
    SCROLLING = 5
    WAIT_SYNC = 6

    WAIT_STUD = 7
    STUD_SCROLL = 8
    STUD_END = 9

    STUD = -1

    def __init__(
        self,
        image_composition,
        service,
        previous_service,
        scroll_delay,
        synchroniser,
        device,
        position,
        controller,
    ):
        self.speed = Args.Speed
        self.position = position
        self.Controller = controller
        self.device = device

        self.image_composition = image_composition
        self.rectangle = ComposableImage(
            RectangleCover(device).image, position=(0, 16 * position + 16)
        )
        self.CurrentService = service

        self.generateCard(service)

        self.IStaticOld = ComposableImage(
            StaticTextImage(device, service, previous_service).image,
            position=(0, 16 * position),
        )

        self.image_composition.add_image(self.IStaticOld)
        self.image_composition.add_image(self.rectangle)

        self.max_pos = self.IDestination.width
        self.image_y_posA = 0
        self.image_x_pos = 0
        self.partner = None

        self.delay = scroll_delay
        self.ticks = 0
        self.state = self.OPENING_SCROLL if service.ID != "0" else self.STUD
        self.synchroniser = synchroniser
        self.render()
        self.synchroniser.ready(self)

    def generateCard(self, service):
        self.displayTimeTemp = TextImage(self.device, service.DisplayTime)
        IDestinationTemp = TextImageComplex(
            self.device, service.Destination, service.Via, self.displayTimeTemp.width
        )

        self.IDestination = ComposableImage(
            IDestinationTemp.image.crop((0, 0, IDestinationTemp.width + 10, 16)),
            position=(
                45 if Args.ShowIndex or Args.LargeLineName else 30,
                16 * self.position,
            ),
        )
        self.IServiceNumber = ComposableImage(
            TextImageServiceNumber(self.device, service.ServiceNumber).image.crop(
                (0, 0, 45 if Args.ShowIndex or Args.LargeLineName else 30, 16)
            ),
            position=(0, 16 * self.position),
        )
        self.IDisplayTime = ComposableImage(
            self.displayTimeTemp.image,
            position=(
                self.device.width - self.displayTimeTemp.width,
                16 * self.position,
            ),
        )

    def updateCard(self, newService):
        self.state = self.SCROLL_DECIDER
        self.synchroniser.ready(self)
        self.image_composition.remove_image(self.IDisplayTime)
        self.CurrentService = newService

        self.displayTimeTemp = TextImage(self.device, newService.DisplayTime)
        self.IDisplayTime = ComposableImage(
            self.displayTimeTemp.image,
            position=(
                self.device.width - self.displayTimeTemp.width,
                16 * self.position,
            ),
        )

        self.image_composition.add_image(self.IDisplayTime)
        self.image_composition.refresh()

    def changeCard(self, newService):
        if newService.ID == "0" and self.CurrentService.ID == "0":
            self.state = self.STUD
            self.synchroniser.ready(self)
            return

        self.synchroniser.busy(self)
        self.IStaticOld = ComposableImage(
            StaticTextImage(self.device, newService, self.CurrentService).image,
            position=(0, 16 * self.position),
        )

        self.image_composition.add_image(self.IStaticOld)
        self.image_composition.add_image(self.rectangle)

        # Safely remove images if they exist
        if self.CurrentService.ID != "0":
            self._safe_remove_image(self.IDestination)
            self._safe_remove_image(self.IServiceNumber)
            self._safe_remove_image(self.IDisplayTime)
            if hasattr(self, "IDestination"):
                del self.IDestination
            if hasattr(self, "IServiceNumber"):
                del self.IServiceNumber
            if hasattr(self, "IDisplayTime"):
                del self.IDisplayTime

        if self.partner is not None and self.partner.CurrentService.ID != "0":
            self.partner.refresh()

        self.image_composition.refresh()

        self.generateCard(newService)
        self.CurrentService = newService
        self.max_pos = self.IDestination.width
        self.state = self.WAIT_STUD if (newService.ID == "0") else self.WAIT_OPENING

    # Add this helper method to ScrollTime class
    def _safe_remove_image(self, image):
        """Safely removes an image from composition if it exists."""
        try:
            if image in self.image_composition.composed_images:
                self.image_composition.remove_image(image)
        except:
            pass  # Image wasn't in the composition

    def delete(self):
        self._safe_remove_image(self.IStaticOld)
        self._safe_remove_image(self.rectangle)
        self._safe_remove_image(self.IDestination)
        self._safe_remove_image(self.IServiceNumber)
        self._safe_remove_image(self.IDisplayTime)
        self.image_composition.refresh()

    #
    # ────────────────── ASYNC TICK ──────────────────
    #
    async def tick(self):
        """
        Called each frame by the board. We must be async so we can await
        self.Controller.requestCardChange(...).
        """
        # Update X min till arrival
        if self.CurrentService.TimePassedStatic() and self.state in (
            self.SCROLL_DECIDER,
            self.SCROLLING_WAIT,
            self.SCROLLING,
            self.WAIT_SYNC,
        ):
            self.image_composition.remove_image(self.IDisplayTime)
            self.CurrentService.DisplayTime = self.CurrentService.GetDisplayTime()
            self.displayTimeTemp = TextImage(
                self.device, self.CurrentService.DisplayTime
            )
            self.IDisplayTime = ComposableImage(
                self.displayTimeTemp.image,
                position=(
                    self.device.width - self.displayTimeTemp.width,
                    16 * self.position,
                ),
            )
            self.image_composition.add_image(self.IDisplayTime)
            self.image_composition.refresh()

        if self.state == self.WAIT_OPENING:
            if not self.is_waiting():
                self.state = self.OPENING_SCROLL
        elif self.state == self.OPENING_SCROLL:
            if self.image_y_posA < 16:
                self.render()
                self.image_y_posA += self.speed
            else:
                self.state = self.OPENING_END

        elif self.state == self.OPENING_END:
            self.image_x_pos = 0
            self.image_y_posA = 0
            self.image_composition.remove_image(self.IStaticOld)
            self.image_composition.remove_image(self.rectangle)
            del self.IStaticOld

            self.image_composition.add_image(self.IDestination)
            self.image_composition.add_image(self.IServiceNumber)
            self.image_composition.add_image(self.IDisplayTime)
            self.render()
            self.synchroniser.ready(self)
            self.state = self.SCROLL_DECIDER

        elif self.state == self.SCROLL_DECIDER:
            if self.synchroniser.is_synchronised():
                if not self.is_waiting():
                    if self.synchroniser.is_synchronised():
                        self.synchroniser.busy(self)
                        if Args.ReducedAnimations:
                            self.state = self.WAIT_SYNC
                        elif self.CurrentService.ID == "0":
                            self.synchroniser.ready(self)
                            self.state = self.STUD
                        else:
                            self.state = self.SCROLLING_WAIT

        elif self.state == self.SCROLLING_WAIT:
            if not self.is_waiting():
                self.state = self.SCROLLING

        elif self.state == self.SCROLLING:
            if self.image_x_pos < self.max_pos:
                self.render()
                self.image_x_pos += self.speed
            else:
                self.state = self.WAIT_SYNC

        elif self.state == self.WAIT_SYNC:
            if self.image_x_pos != 0:
                self.image_x_pos = 0
                self.render()
            else:
                if not self.is_waiting():
                    # Must await the requestCardChange call
                    await self.Controller.requestCardChange(self, self.position + 1)

        elif self.state == self.WAIT_STUD:
            if not self.is_waiting():
                self.state = self.STUD_SCROLL

        elif self.state == self.STUD_SCROLL:
            if self.image_y_posA < 16:
                self.render()
                self.image_y_posA += self.speed
            else:
                self.state = self.STUD_END

        elif self.state == self.STUD_END:
            self.image_x_pos = 0
            self.image_y_posA = 0
            self.image_composition.remove_image(self.IStaticOld)
            self.image_composition.remove_image(self.rectangle)
            del self.IStaticOld
            self.render()
            self.synchroniser.ready(self)
            self.state = self.STUD

        elif self.state == self.STUD:
            if not self.is_waiting():
                # Must await here as well
                await self.Controller.requestCardChange(self, self.position + 1)

    def render(self):
        if self.state in (self.SCROLLING, self.WAIT_SYNC):
            self.IDestination.offset = (self.image_x_pos, 0)
        if self.state in (self.OPENING_SCROLL, self.STUD_SCROLL):
            self.IStaticOld.offset = (0, self.image_y_posA)

    def refresh(self):
        if (
            hasattr(self, "IDestination")
            and hasattr(self, "IServiceNumber")
            and hasattr(self, "IDisplayTime")
        ):
            self._safe_remove_image(self.IDestination)
            self._safe_remove_image(self.IServiceNumber)
            self._safe_remove_image(self.IDisplayTime)
            self.image_composition.add_image(self.IDestination)
            self.image_composition.add_image(self.IServiceNumber)
            self.image_composition.add_image(self.IDisplayTime)

    def addPartner(self, partner):
        self.partner = partner

    def is_waiting(self):
        self.ticks += 1
        if self.ticks > self.delay:
            self.ticks = 0
            return False
        return True


def Splash(device):
    if Args.SplashScreen:
        with canvas(device) as draw:
            draw.multiline_text(
                (64, 10),
                "Departure Board",
                font=ImageFont.truetype(
                    "%s/resources/Bold.ttf"
                    % (
                        os.path.dirname(
                            os.path.abspath(inspect.getfile(inspect.currentframe()))
                        )
                    ),
                    20,
                ),
                align="center",
            )
            draw.multiline_text(
                (45, 35),
                "Apdapted from Jonathan Foot",
                font=ImageFont.truetype(
                    "%s/resources/Skinny.ttf"
                    % (
                        os.path.dirname(
                            os.path.abspath(inspect.getfile(inspect.currentframe()))
                        )
                    ),
                    15,
                ),
                align="center",
            )
        time.sleep(
            2
        )  # Wait such a long time to allow the device to startup and connect to a WIFI source first.


class boardFixed:
    def __init__(self, image_composition, scroll_delay, device):
        self.device = device
        self.image_composition = image_composition
        self.scroll_delay = scroll_delay
        self.synchroniser = Synchroniser()
        self.Services = []  # full list of fetched services
        self.State = "alive"
        self.ticks = 0

        # Add locks for different resources
        self.services_lock = asyncio.Lock()  # For protecting Services list updates
        self.display_lock = asyncio.Lock()  # For protecting display updates
        self.rotation_lock = asyncio.Lock()  # For protecting rotation index updates

        # Global pointer for cycling through the rotating services.
        self.rotating_index = 0
        # Flag to ensure a coordinated update of rows 2 and 3.
        self.rotating_update_pending = False

        # These will hold our three ScrollTime rows.
        self.top = None  # Row 1 (pinned)
        self.middle = None  # Row 2
        self.bottom = None  # Row 3

        # Prepare a fallback "No Services" image.
        no_service_image = NoService(device)
        self.NoServices = ComposableImage(
            no_service_image.image,
            position=(
                device.width // 2 - no_service_image.width // 2,
                device.height // 2 - no_service_image.height // 2,
            ),
        )

    async def first_fetch(self):
        """
        Called once at startup to fetch data and build the initial cards.
        """
        await self.fetch_and_sort_services()
        self.set_initial_cards()

    async def fetch_and_sort_services(self):
        """
        Fetch new service data asynchronously and sort by earliest departure.
        Uses a lock to prevent concurrent modifications to the Services list.
        """
        async with self.services_lock:
            # Store current service IDs before fetching
            current_ids = []
            if self.top and self.top.CurrentService.ID != "0":
                current_ids.append(self.top.CurrentService.ID)
            if self.middle and self.middle.CurrentService.ID != "0":
                current_ids.append(self.middle.CurrentService.ID)
            if self.bottom and self.bottom.CurrentService.ID != "0":
                current_ids.append(self.bottom.CurrentService.ID)

            # Fetch new data
            data = await LiveTime.GetDataAsync()
            data.sort(
                key=lambda svc: svc.ExptArrival if svc.ExptArrival else svc.SchArrival
            )

            # Check for changes
            old_services = self.Services.copy() if hasattr(self, "Services") else []
            self.Services = data

            return old_services != self.Services

    def split_pinned_rotating(self):
        """
        Splits self.Services into:
          - pinned: The earliest service (Services[0]) or None if no services.
          - rotating: All services after the pinned one (duplicates removed, and none with the same ID as pinned).
        """
        if len(self.Services) == 0:
            return None, []
        pinned = self.Services[0]
        rotating = self.Services[1:]
        # Exclude any service with the same ID as the pinned service.
        rotating = [svc for svc in rotating if svc.ID != pinned.ID]
        # Remove duplicates from rotating.
        unique_rotating = []
        seen_ids = set()
        for svc in rotating:
            if svc.ID not in seen_ids:
                unique_rotating.append(svc)
                seen_ids.add(svc.ID)
        return pinned, unique_rotating

    def set_initial_cards(self):
        """
        Build the three ScrollTime rows using the current Services.
          - Row 1 is pinned to the earliest service.
          - Rows 2 and 3 are built from the rotating list.
          - The global rotating pointer is reset.
        """
        pinned, rotating = self.split_pinned_rotating()
        # Build row 1 (pinned). If no pinned service, show a blank.
        self.top = ScrollTime(
            image_composition=self.image_composition,
            service=pinned if pinned else LiveTimeStud(),
            previous_service=LiveTimeStud(),
            scroll_delay=self.scroll_delay,
            synchroniser=self.synchroniser,
            device=self.device,
            position=0,
            controller=self,
        )
        # For row 2, use the first rotating service if available.
        svc2 = rotating[0] if len(rotating) > 0 else LiveTimeStud()
        self.middle = ScrollTime(
            image_composition=self.image_composition,
            service=svc2,
            previous_service=LiveTimeStud(),
            scroll_delay=self.scroll_delay,
            synchroniser=self.synchroniser,
            device=self.device,
            position=1,
            controller=self,
        )
        # For row 3, use the second rotating service if available.
        svc3 = rotating[1] if len(rotating) > 1 else LiveTimeStud()
        self.bottom = ScrollTime(
            image_composition=self.image_composition,
            service=svc3,
            previous_service=LiveTimeStud(),
            scroll_delay=self.scroll_delay,
            synchroniser=self.synchroniser,
            device=self.device,
            position=2,
            controller=self,
        )
        self.top.addPartner(self.middle)
        self.middle.addPartner(self.bottom)
        # Reset the rotating pointer.
        self.rotating_index = 0

    async def update_display_with_new_data(self):
        """
        Updates the display with new data while trying to preserve the current view state.
        """
        async with self.display_lock:
            # If this is the first time, do a full initialization
            if self.top is None:
                self.set_initial_cards()
                return

            # Get the pinned and rotating services
            async with self.services_lock:
                pinned, rotating = self.split_pinned_rotating()

                # Get currently visible services for continuity
                visible_services = []
                if self.top and self.top.CurrentService.ID != "0":
                    visible_services.append(self.top.CurrentService.ID)
                if self.middle and self.middle.CurrentService.ID != "0":
                    visible_services.append(self.middle.CurrentService.ID)
                if self.bottom and self.bottom.CurrentService.ID != "0":
                    visible_services.append(self.bottom.CurrentService.ID)

                # Update top row (always shows the earliest service if FixToArrive is True)
                if Args.FixToArrive:
                    if pinned:
                        # If the pinned service is different from what's currently shown, update it
                        if not self.top or self.top.CurrentService.ID != pinned.ID:
                            self.top.changeCard(pinned)
                    else:
                        self.top.changeCard(LiveTimeStud())

                # For rotating services, try to maintain the current view by finding where
                # the currently displayed services are in the new list
                if len(rotating) > 0:
                    # Try to find the current middle service in the new rotating list
                    current_middle_idx = -1
                    if self.middle and self.middle.CurrentService.ID != "0":
                        for i, svc in enumerate(rotating):
                            if svc.ID == self.middle.CurrentService.ID:
                                current_middle_idx = i
                                break

                    if current_middle_idx >= 0:
                        # Found the current middle service - keep the same position
                        self.rotating_index = current_middle_idx
                    elif len(visible_services) > 0:
                        # Current service not found, but try to find any of the currently
                        # visible services in the new list
                        for vis_id in visible_services:
                            for i, svc in enumerate(rotating):
                                if svc.ID == vis_id:
                                    self.rotating_index = i
                                    break

                    # Update middle and bottom rows based on the determined rotating_index
                    idx_middle = self.rotating_index % len(rotating)
                    idx_bottom = (
                        (self.rotating_index + 1) % len(rotating)
                        if len(rotating) > 1
                        else -1
                    )

                    self.middle.changeCard(rotating[idx_middle])
                    if idx_bottom >= 0:
                        self.bottom.changeCard(rotating[idx_bottom])
                    else:
                        self.bottom.changeCard(LiveTimeStud())
                else:
                    # No rotating services available
                    self.middle.changeCard(LiveTimeStud())
                    self.bottom.changeCard(LiveTimeStud())

    async def tick(self):
        """
        Called repeatedly to:
        1. Animate each row
        2. Force a data fetch if enough time has passed
        3. Handle a no-services state
        4. Force rotation cycle every N ticks
        """
        # If the board hasn't been initialized yet, exit
        if self.top is None:
            return

        # Animate each row
        await self.top.tick()
        await self.middle.tick()
        await self.bottom.tick()

        # Force rotation every N ticks (adjust as needed)
        self.ticks += 1
        if self.ticks >= Args.Delay * 4:  # Adjust multiplier as needed
            self.ticks = 0
            await self.force_rotation_cycle()

        # Forced time-based fetch check
        if LiveTime.TimePassed():
            try:
                changed = await self.fetch_and_sort_services()

                # Only update the display if data has actually changed
                if changed:
                    await self.update_display_with_new_data()
            except Exception as e:
                print("Error fetching new data:", e)

        # Handle the "no services" case
        if len(self.Services) == 0:
            if self.ticks == 0:
                self.image_composition.add_image(self.NoServices)
            if not self.is_waiting():
                self.top.delete()
                self.middle.delete()
                self.bottom.delete()
                self.image_composition.remove_image(self.NoServices)
                self.State = "dead"
            return

    def is_waiting(self):
        """
        A simple recovery delay mechanism.
        """
        self.ticks += 1
        if self.ticks > Args.RecoveryTime:
            self.ticks = 0
            return False
        return True

    async def force_rotation_cycle(self):
        """
        Force a complete rotation of the visible services
        Protected by rotation_lock to prevent concurrent rotations
        """
        async with self.rotation_lock:
            if len(self.Services) <= 1:  # Don't rotate if not enough services
                return

            async with self.services_lock:
                pinned, rotating = self.split_pinned_rotating()

            if len(rotating) <= 1:  # Don't rotate if not enough rotating services
                return

            # Advance to next pair of services
            self.rotating_index = (self.rotating_index + 1) % len(rotating)

            # Get the services to display
            middle_service = rotating[self.rotating_index]
            bottom_service = rotating[(self.rotating_index + 1) % len(rotating)]

            # Update the cards - need display lock
            print(
                f"Force rotating to services {middle_service.ServiceNumber} and {bottom_service.ServiceNumber}"
            )
            async with self.display_lock:
                self.middle.changeCard(middle_service)
                self.bottom.changeCard(bottom_service)

    async def requestCardChange(self, card, row):
        async with self.rotation_lock:
            # If it's time for a new fetch, do that.
            if LiveTime.TimePassed():
                try:
                    await self.fetch_and_sort_services()  # This already has its own lock
                    async with self.display_lock:
                        self.set_initial_cards()
                    return
                except Exception as e:
                    print("Error fetching new data:", e)
                    return

            async with self.services_lock:
                pinned, rotating = self.split_pinned_rotating()

            # For the fixed first row, simply update the display time.
            if row == 1 and Args.FixToArrive:
                async with self.display_lock:
                    self.top.refresh()
                return

            # Only allow the middle row (row 2) to trigger a rotating update.
            if row != 2:
                return

            if self.rotating_update_pending:
                return  # Already updating; skip duplicate calls.
            self.rotating_update_pending = True

            try:
                # Rest of the method with appropriate lock usage
                async with self.display_lock:

                    # Ensure we have at least one rotating service
                    if len(rotating) == 0:
                        # No rotating services available, show blanks
                        self.middle.changeCard(LiveTimeStud())
                        self.bottom.changeCard(LiveTimeStud())
                    elif len(rotating) == 1:
                        # Only one rotating service, show it in row 2
                        self.middle.changeCard(rotating[0])
                        self.bottom.changeCard(LiveTimeStud())
                    else:
                        # Multiple rotating services, update using our rotating index
                        # Calculate the indices for the two rows
                        idx_middle = self.rotating_index % len(rotating)
                        idx_bottom = (self.rotating_index + 1) % len(rotating)

                        # Update both rows
                        self.middle.changeCard(rotating[idx_middle])
                        self.bottom.changeCard(rotating[idx_bottom])

                        # Increment rotating_index to show next set of services in the next cycle
                        self.rotating_index = (self.rotating_index + 1) % len(rotating)
                        # Debug output to verify cycling
                        print(
                            f"Updated rotating index to {self.rotating_index}, showing services {idx_middle} and {idx_bottom}"
                        )
            finally:
                self.rotating_update_pending = False


def is_time_between():
    # If check time is not given, default to current UTC time
    check_time = datetime.now().time()
    if Args.InactiveHours[0] < Args.InactiveHours[1]:
        return (
            check_time >= Args.InactiveHours[0] and check_time <= Args.InactiveHours[1]
        )
    else:  # crosses midnight
        return (
            check_time >= Args.InactiveHours[0] or check_time <= Args.InactiveHours[1]
        )


# Draws the clock and tells the rest of the display next frame wanted


async def display(board, device, image_composition, FontTime):
    # Now that board.tick() is async, we do:
    await board.tick()

    # Everything else can stay as synchronous as needed
    msgTime = str(
        datetime.now().strftime("%H:%M" if (Args.TimeFormat == 24) else "%I:%M")
    )

    # The luma.core 'canvas' context manager is synchronous,
    # but it's perfectly fine to use it inside an async function.
    with canvas(device, background=image_composition()) as draw:
        image_composition.refresh()
        draw.multiline_text(
            (
                (device.width - int(draw.textlength(msgTime, FontTime))) / 2,
                device.height - 16,
            ),
            msgTime,
            font=FontTime,
            align="center",
        )


async def main():
    DisplayParser = cmdline.create_parser(
        description="Dynamically connect to either a virtual or physical display."
    )
    device = cmdline.create_device(
        DisplayParser.parse_args(
            [
                "--display",
                str(Args.Display),
                "--interface",
                "spi",
                "--width",
                "256",
                "--rotate",
                str(Args.Rotation),
            ]
        )
    )
    if Args.Display == "gifanim":
        device._filename = str(Args.filename)
        device._max_frames = int(Args.maxframes)

    image_composition = ImageComposition(device)
    FontTime = ImageFont.truetype(
        "%s/resources/time.otf"
        % (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))),
        16,
    )
    device.contrast(255)
    energyMode = "normal"
    StartUpDate = datetime.now().date()
    # Show splash once at startup
    Splash(device)

    # Start your blink thread
    BlinkState.start()

    board = boardFixed(image_composition, Args.Delay, device)

    # Perform the initial fetch asynchronously so board has data
    await board.first_fetch()

    # The main update loop
    while True:
        # If the board died, re-init
        if board.State == "dead":
            del board
            board = boardFixed(image_composition, Args.Delay, device)
            device.clear()
            await board.fetch_and_sort_services()
            board.set_initial_cards()

        # Handle energy saver logic
        if Args.EnergySaverMode != "none" and is_time_between():
            # If within inactive hours
            if Args.EnergySaverMode == "dim":
                if energyMode == "normal":
                    device.contrast(15)
                    energyMode = "dim"
                await display(board, device, image_composition, FontTime)
            elif Args.EnergySaverMode == "off":
                if energyMode == "normal":
                    device.clear()
                    device.hide()
                    energyMode = "off"
        else:
            # Normal mode
            if energyMode != "normal":
                device.contrast(255)
                if energyMode == "off":
                    device.show()
                    Splash()  # optional re-splash
                    board = boardFixed(image_composition, Args.Delay, device)
                    await board.first_fetch()
                energyMode = "normal"
            # Draw the clock and update the display
            await display(board, device, image_composition, FontTime)

        # Replace old 'time.sleep(0.02)' with a non-blocking pause
        await asyncio.sleep(0.02)


# Standard async/await entry point
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        BlinkState.stop()
