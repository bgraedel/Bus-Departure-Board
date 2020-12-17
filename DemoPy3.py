# This software was produced by Jonathan Foot (c) 2021, all rights reserved.
# Project Website : https://departureboard.jonathanfoot.com
# Documentation   : https://jonathanfoot.com/Projects/DepartureBoard
# Description     : This program allows you to display demo a bus departure board for an example Reading Buses stop. 
# Python 3 Required.

import time
import inspect,os
import sys
import argparse
from urllib.request import urlopen
from PIL import ImageFont, Image, ImageDraw
from luma.core.render import canvas
from luma.core.interface.serial import spi
from luma.core import cmdline
from lxml import objectify
from datetime import datetime
from luma.core.image_composition import ImageComposition, ComposableImage

###
# Below Declares all the program optional and compulsory settings/ start up paramters. 
###
## Start Up Paramarter Checks
# Checks value is greater than Zero.
def check_positive(value):
	try:
		ivalue = int(value)
		if ivalue <= 0:
			raise argparse.ArgumentTypeError("%s is invalid, value must be an integer value greater than 0." % value)
		return ivalue
	except:
		raise argparse.ArgumentTypeError("%s is invalid, value must be an integer value greater than 0." % value)

# Checks string is a valid time range, in the format of "00:00-24:00"
def check_time(value):
	try:
		datetime.strptime(value.split("-")[0], '%H:%M').time()
		datetime.strptime(value.split("-")[1], '%H:%M').time()
	except:
		raise argparse.ArgumentTypeError("%s is invalid, value must be in the form of XX:XX-YY:YY, where the values are in 24hr format." % value)
	return [datetime.strptime(value.split("-")[0], '%H:%M').time(),  datetime.strptime(value.split("-")[1], '%H:%M').time()]

## Defines all optional paramaters
parser = argparse.ArgumentParser(description='Reading Buses Live Departure Board, to run the program you will need to pass it all of the required paramters and you may wish to pass any optional paramters.')
parser.add_argument("-t","--TimeFormat", help="Do you wish to use 24hr or 12hr time format; default is 24hr.", type=int,choices=[12,24],default=24)
parser.add_argument("-v","--Speed", help="What speed do you want the text to scroll at on the display; default is 3, must be greater than 0.", type=check_positive,default=3)
parser.add_argument("-d","--Delay", help="How long the display will pause before starting the next animation; default is 30, must be greater than 0.", type=check_positive,default=30)
parser.add_argument("-r","--RecoveryTime", help="How long the display will wait before attempting to get new data again after previously failing; default is 100, must be greater than 0.", type=check_positive,default=100)
parser.add_argument("-n","--NumberOfCards", help="The maximum number of cards you will see before forcing a new data retrieval, a limit is recommend to prevent cycling through data which may become out of data or going too far into scheduled buses; default is 9, must be greater than 0.", type=check_positive,default=9)
parser.add_argument("-y","--Rotation", help="Defines which way up the screen is rendered; default is 0", type=int,default=0,choices=[0,2])
parser.add_argument("-l","--RequestLimit", help="Defines the minium amount of time the display must wait before making a new data request; default is 55(seconds)", type=check_positive,default=55)
parser.add_argument("-z","--StaticUpdateLimit", help="Defines the amount of time the display will wait before updating the expected arrival time (based upon it's last known predicted arrival time); default is  15(seconds), this should be lower than your 'RequestLimit'", type=check_positive,default=15)
parser.add_argument("-e","--EnergySaverMode", help="To save screen from burn in and prolong it's life it is recommend to have energy saving mode enabled. 'off' is default, between the hours set the screen will turn off. 'dim' will turn the screen brightness down, but not completely off. 'none' will do nothing and leave the screen on; this is not recommend, you can change your active hours instead.", type=str,choices=["none","dim","off"],default="off")
parser.add_argument("-i","--InactiveHours", help="The period of time for which the display will go into 'Energy Saving Mode' if turned on; default is '23:00-07:00'", type=check_time,default="23:00-07:00")
parser.add_argument("-u","--UpdateDays", help="The number of days for which the Pi will wait before rebooting and checking for a new update again during your energy saving period; default 3 days.", type=check_positive, default=3)
parser.add_argument("-x","--ExcludeServices", default="", help="List any services you do not wish to view. Make sure to capitalise correctly and simply put a single space between each; default is nothing, ie show every service.",  nargs='*')
parser.add_argument('--ShowIndex', dest='ShowIndex', action='store_true',help="Do you wish to see index position for each service due to arrive.")
parser.add_argument("--ReducedAnimations", help="If you wish to stop the Via animation and cycle faster through the services use this tag to turn the animation off.", dest='ReducedAnimations', action='store_true')
parser.add_argument("--UnfixNextToArrive",dest='FixToArrive', action='store_false', help="Keep the bus sonnest to next arrive at the very top of the display until it has left; by default true")
parser.add_argument("--HideUnknownVias", help="If the API does not report any known via route a placeholder of 'Via Central Reading' is used. If you wish to stop the animation for unknowns use this tag.", dest='HideUnknownVias', action='store_true')
parser.add_argument('--no-splashscreen', dest='SplashScreen', action='store_false',help="Do you wish to see the splash screen at start up; recommended and on by default.")
parser.add_argument("--Display", default="ssd1322", choices=['ssd1322','pygame','capture','gifanim'], help="Used for development purposes, allows you to switch from a physical display to a virtual emulated one; default 'ssd1322'")
parser.add_argument("--max-frames", default=60,dest='maxframes', type=check_positive, help="Used only when using gifanim emulator, sets how long the gif should be.")
parser.add_argument("--no-console-output",dest='NoConsole', action='store_true', help="Used to stop the program outputting anything to console to isn't an error message, you might want to do this if your logging the program output into a file to record crashes.")

Args = parser.parse_args()

## Defines all the programs "global" variables 
# Defines the basic font used throughout most of the text boxes in the program
BasicFont = ImageFont.truetype("%s/resources/lower.ttf" %(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))) ),14)
# Defines the place holder via message when one can not be found/ given in the API.
GenericVia = "Via Central Reading"

###
# Below contains the class which is used to reperesent one instance of a service record. It is also responsible for getting the information from the Reading Buses API.
###
# Used to create a blank object, needed in start-up or when there are less than 3 services currently scheduled. 
class LiveTimeStud():
	def __init__(self):
		self.ServiceNumber = " "
		self.Destination = " "
		self.DisplayTime = " "
		self.SchArrival = " "
		self.ExptArrival = " "
		self.Via = " "
		self.ID =  "0"
	
	def TimePassedStatic(self):
		return False
		
	
# Used to get live data from the Reading Buses API and represent a specific services and it's details.
class LiveTime(object):
	# The last time an API call was made to get new data.
	LastUpdate = datetime.now()
	
	# * Change this method to implement your own API *
	def __init__(self, Data, Index):
		self.ServiceNumber = "%s.%s" % (Index + 1, str(Data.LineRef)) if Args.ShowIndex else str(Data.LineRef)
		self.Destination = str(Data.DestinationName)
		self.SchArrival = str(Data.MonitoredCall.AimedArrivalTime).split("+")[0]
		self.ExptArrival = str(getattr( Data.MonitoredCall, "ExpectedArrivalTime", "")).split("+")[0]
		# The "Via" message, which lists where the service will go through, if unknown use generic message.
		self.Via = str(getattr(Data, "Via", GenericVia))
		# The formated string containing the time of arrival, to be printed on the display screen.
		self.DisplayTime = self.GetDisplayTime()
		self.ID =  str(Data.FramedVehicleJourneyRef.DatedVehicleJourneyRef)
	
	#Returns the value to display the time on the board.
	def GetDisplayTime(self):
		# Last time the display screen was updated to reflect the new time of arrival.
		self.LastStaticUpdate = datetime.now()
		# If unknown predicted time use scheduled (time tabled) time.
		if self.ExptArrival == "":
			return " " + datetime.strptime(self.SchArrival, '%Y-%m-%dT%H:%M:%S').strftime("%H:%M" if (Args.TimeFormat==24) else  "%I:%M")
		else:
			Diff =  (datetime.strptime(self.ExptArrival, '%Y-%m-%dT%H:%M:%S') - datetime.now()).total_seconds() / 60
			if Diff <= 2:
				return ' Due'
			# If more than 15min away show the time as 'XX:XX', else show it as a count down in 'X min'
			if Diff >=15 :
				return ' ' + datetime.strptime(self.SchArrival, '%Y-%m-%dT%H:%M:%S').strftime("%H:%M" if (Args.TimeFormat==24) else  "%I:%M")
			return  ' %d min' % Diff

	# Returns true or false dependent upon if the last time an API data call was made was over the request limit; to prevent spamming the API feed.
	@staticmethod
	def TimePassed():
		return (datetime.now() - LiveTime.LastUpdate).total_seconds() > Args.RequestLimit

	# Return true or false dependent upon if the last time the display was updated was over the static update limit. This prevents updating the display to frequently to increase performance.
	def TimePassedStatic(self):
		return ("min" in self.DisplayTime) and (datetime.now() - self.LastStaticUpdate).total_seconds() > Args.StaticUpdateLimit 

	# Calls the API and gets the data from it, returning a list of LiveTime objects to be used in the program.
	# * Change this method to implement your own API *
	@staticmethod
	def GetData():
		LiveTime.LastUpdate = datetime.now()
		services = []

		try:
			with urlopen("https://jonathanfoot.com/Projects/DepartureBoard/Assets/demoFile.xml") as conn:
				rawServices = objectify.fromstring(conn.read())
			
				# The Reading Buses API sometimes reports the same bus multiple times. To work around this we need to check if we have already found it.
				for root in rawServices.ServiceDelivery.StopMonitoringDelivery.MonitoredStopVisit:
					service = root.MonitoredVehicleJourney
					exists = False
					for current in services:
						if current.ID == service.FramedVehicleJourneyRef.DatedVehicleJourneyRef:
							exists = True
							break
					# If not already recorded and not in the excluded services list add it.
					if exists == False and str(service.LineRef) not in Args.ExcludeServices:
						# Convert the custom Reading Buses API object into a LiveTime object and add it to the list.
						services.append(LiveTime(service, len(services)))
			return services
		except Exception as e:
			print(str(e))
			return []


###
# Below contains everything for the drawing on the board.
# All text must be converted into Images, for the image to be displayed on the display.
###

# Used to create the time and service number on the board or any other basic text box.
class TextImage():
	def __init__(self, device, text):
		self.image = Image.new(device.mode, (device.width, 16))
		draw = ImageDraw.Draw(self.image)
		draw.text((0, 0), text, font=BasicFont, fill="white")
	
		self.width = 5 + draw.textsize(text, BasicFont)[0]
		self.height = 5 + draw.textsize(text, BasicFont)[1]
		del draw

# Used to create the destination and via board.
class TextImageComplex():
	def __init__(self, device, destination, via, startOffset):
		self.image = Image.new(device.mode, (device.width*2, 16))
		draw = ImageDraw.Draw(self.image)
		draw.text((0, 0), destination, font=BasicFont, fill="white")
		draw.text((device.width - startOffset, 0), via, font=BasicFont, fill="white")
			
		self.width = device.width + draw.textsize(via, BasicFont)[0]  - startOffset
		self.height = 16
		del draw

# Used for the opening animation, creates a static two lines of the new and previous service.
class StaticTextImage():
	def __init__(self, device, service, previous_service):			
		self.image = Image.new(device.mode, (device.width, 32))
		draw = ImageDraw.Draw(self.image)
		displayTimeTempPrevious = TextImage(device, previous_service.DisplayTime)
		displayTimeTemp = TextImage(device, service.DisplayTime)

		draw.text((0, 16), service.ServiceNumber, font=BasicFont, fill="white")
		draw.text((device.width - displayTimeTemp.width, 16), service.DisplayTime, font=BasicFont, fill="white")
		draw.text((45 if Args.ShowIndex else 30, 16), service.Destination, font=BasicFont, fill="white")	

		draw.text((45 if Args.ShowIndex else 30, 0), previous_service.Destination, font=BasicFont, fill="white")	
		draw.text((0, 0), previous_service.ServiceNumber, font=BasicFont, fill="white")
		draw.text((device.width - displayTimeTempPrevious.width, 0), previous_service.DisplayTime, font=BasicFont, fill="white")
	
		self.width = device.width 
		self.height = 32
		del draw

# Used to draw a black cover over hidden stuff.
class RectangleCover():
	def __init__(self, device):		
		w = device.width
		h = 16
			
		self.image = Image.new(device.mode, (w, h))
		draw = ImageDraw.Draw(self.image)
		draw.rectangle((0, 0, device.width,16), outline="black", fill="black")

		del draw
		self.width = w 
		self.height = h

# Error message displayed when no data can be found.
class NoService():
	def __init__(self, device):		
		w = device.width
		h = 16
		msg = "No Scheduled Services Found"
		self.image = Image.new(device.mode, (w, h))
		draw = ImageDraw.Draw(self.image)
		draw.text((0, 0), msg, font=BasicFont, fill="white")
	
		self.width = draw.textsize(msg, font=BasicFont)[0]
		self.height = draw.textsize(msg, font=BasicFont)[1]
		del draw

###
## Synchronizer, used to keep track what is busy doing work and what is ready to do more work.
###

# Used to ensure that only 1 animation is playing at any given time, apart from at the start; where all three can animate in.
class Synchroniser():
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


###
## Below contains the class which represents a single row on the bus display, a LiveTime object contains all the information on a service and is then wrapped up in a ScrollTime Object
## This object contains the state of the object, such as if it is in an animation and what should be displayed to the display.
###

class ScrollTime():
	WAIT_OPENING = 0
	OPENING_SCROLL = 1
	OPENING_END  = 2
	SCROLL_DECIDER = 3
	SCROLLING_WAIT = 4
	SCROLLING = 5
	WAIT_SYNC = 6
	WAIT_STUD = 7
	STUD_SCROLL = 8
	STUD_END = 9

	STUD = -1
	
	def __init__(self, image_composition, service, previous_service, scroll_delay, synchroniser, device, position, controller):
		self.speed = Args.Speed
		self.position = position
		self.Controller = controller
		
		self.image_composition = image_composition
		self.rectangle = ComposableImage(RectangleCover(device).image, position=(0,16 * position + 16))
		self.CurrentService = service
		
		self.generateCard(service)
		
		self.IStaticOld =  ComposableImage(StaticTextImage(device,service, previous_service).image, position=(0, (16 * position)))
		
		self.image_composition.add_image(self.IStaticOld)
		self.image_composition.add_image(self.rectangle)
		
		self.max_pos = self.IDestination.width
		self.image_y_posA = 0
		self.image_x_pos = 0
		self.device = device
		self.partner = None
			
		self.delay = scroll_delay
		self.ticks = 0
		self.state = self.OPENING_SCROLL if service.ID != 0 else self.STUD
		self.synchroniser = synchroniser
		self.render()
		self.synchroniser.ready(self)

	# Generates all the Images (Text boxes) to be drawn on the display.
	def generateCard(self,service):
		displayTimeTemp = TextImage(device, service.DisplayTime)
		IDestinationTemp  = TextImageComplex(device, service.Destination,service.Via, displayTimeTemp.width)

		self.IDestination =  ComposableImage(IDestinationTemp.image.crop((0,0,IDestinationTemp.width + 10,16)), position=(45 if Args.ShowIndex else 30, 16 * self.position))
		self.IServiceNumber =  ComposableImage(TextImage(device, service.ServiceNumber).image.crop((0,0,45 if Args.ShowIndex else 30,16)), position=(0, 16 * self.position))
		self.IDisplayTime =  ComposableImage(displayTimeTemp.image, position=(device.width - displayTimeTemp.width, 16 * self.position))

	# Called when you have new/updated information from an API call and want to update the objects predicted arrival time.
	def updateCard(self, newService, device):
		self.state = self.SCROLL_DECIDER
		self.synchroniser.ready(self)
		self.image_composition.remove_image(self.IDisplayTime)

		displayTimeTemp = TextImage(device, newService.DisplayTime)
		self.IDisplayTime = ComposableImage(displayTimeTemp.image, position=(device.width - displayTimeTemp.width, 16 * self.position))
	
		self.image_composition.add_image(self.IDisplayTime)
		self.image_composition.refresh()

	# Called when you want to change the row from one service to another.
	def changeCard(self, newService, device):
		if newService.ID == "0" and self.CurrentService.ID == "0":
			self.state = self.STUD
			self.synchroniser.ready(self)
			return 
			
		self.synchroniser.busy(self)
		self.IStaticOld =  ComposableImage(StaticTextImage(device,newService, self.CurrentService).image, position=(0, (16 * self.position)))
	
		self.image_composition.add_image(self.IStaticOld)
		self.image_composition.add_image(self.rectangle)

		if self.CurrentService.ID != "0":
			self.image_composition.remove_image(self.IDestination)
			self.image_composition.remove_image(self.IServiceNumber)
			self.image_composition.remove_image(self.IDisplayTime)
			del self.IDestination
			del self.IServiceNumber
			del self.IDisplayTime

		if self.partner != None and self.partner.CurrentService.ID != "0":
			self.partner.refresh()
			
		self.image_composition.refresh()
		

		self.generateCard(newService)
		self.CurrentService = newService
		self.max_pos = self.IDestination.width
		
		self.state = self.WAIT_STUD if (newService.ID == "0") else self.WAIT_OPENING
		
	# Used when you want to delete the row/card/object.
	def delete(self):
		try:
			self.image_composition.remove_image(self.IStaticOld)
			self.image_composition.remove_image(self.rectangle)
		except:
			pass
		try:
			self.image_composition.remove_image(self.IDestination)
			self.image_composition.remove_image(self.IServiceNumber)
			self.image_composition.remove_image(self.IDisplayTime)
		except:
			pass  
		self.image_composition.refresh() 

	# Called upon each time you want to get the next frame for the display.
	def tick(self):
		#Update X min till arrival.
		if self.CurrentService.TimePassedStatic() and (self.state == self.SCROLL_DECIDER or self.state == self.SCROLLING_WAIT or self.state == self.SCROLLING or self.state == self.WAIT_SYNC):
			self.image_composition.remove_image(self.IDisplayTime)
			self.CurrentService.DisplayTime = self.CurrentService.GetDisplayTime()
			displayTimeTemp = TextImage(device, self.CurrentService.DisplayTime)
			self.IDisplayTime = ComposableImage(displayTimeTemp.image, position=(device.width - displayTimeTemp.width, 16 * self.position))           
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
						if (Args.HideUnknownVias and self.CurrentService.Via == GenericVia) or Args.ReducedAnimations:
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
					self.Controller.requestCardChange(self, self.position + 1)


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
				self.Controller.requestCardChange(self, self.position + 1)
			
		
	# Sets the image offest for the animation, telling it how to render.
	def render(self):
		if(self.state == self.SCROLLING or self.state == self.WAIT_SYNC):
			self.IDestination.offset = (self.image_x_pos, 0)
		if(self.state == self.OPENING_SCROLL or self.state == self.STUD_SCROLL):
			self.IStaticOld.offset= (0,self.image_y_posA)
	
	# Used to reset the image on the display.
	def refresh(self):
		self.image_composition.remove_image(self.IDestination)
		self.image_composition.remove_image(self.IServiceNumber)
		self.image_composition.remove_image(self.IDisplayTime)
		self.image_composition.add_image(self.IDestination)
		self.image_composition.add_image(self.IServiceNumber)
		self.image_composition.add_image(self.IDisplayTime)

	# Used to add a partner; this is the row below it self. Used when needed to tell partner to redraw itself
	# on top of the row above it (layering the text boxes correctly)
	def addPartner(self, partner):
		self.partner = partner

	# Used to add a time delay between animations.
	def is_waiting(self):
		self.ticks += 1
		if self.ticks > self.delay:
			self.ticks = 0
			return False
		return True

###
## Board Controller
## Defines the board which controls what each off the rows in the display will show at any time.
###
class boardFixed():
	def __init__(self, image_composition, scroll_delay, device):
		self.Services = LiveTime.GetData()   
		self.synchroniser = Synchroniser()
		self.scroll_delay = scroll_delay
		self.image_composition = image_composition
		self.device = device
		self.ticks = 0
		self.setInitalCards()
		self.State = "alive"
	
		NoServiceTemp = NoService(device)
		self.NoServices = ComposableImage(NoServiceTemp.image, position=(device.width/2- NoServiceTemp.width/2,device.height/2-NoServiceTemp.height/2))

		self.top.addPartner(self.middel)
		self.middel.addPartner(self.bottom)
	
	# Set up the cards for the initial starting animation.
	def setInitalCards(self):
		self.top = ScrollTime(image_composition, len(self.Services) >= 1 and self.Services[0] or LiveTimeStud(),LiveTimeStud(), self.scroll_delay, self.synchroniser, device, 0, self)
		self.middel = ScrollTime(image_composition, len(self.Services) >= 2 and self.Services[1] or LiveTimeStud(),LiveTimeStud(), self.scroll_delay, self.synchroniser, device, 1,self)
		self.bottom = ScrollTime(image_composition, len(self.Services) >= 3 and self.Services[2] or LiveTimeStud(),LiveTimeStud(), self.scroll_delay, self.synchroniser, device, 2, self)
		self.x = len(self.Services) < 3 and len(self.Services) or 3

	# Called upon every time a new frame is needed.
	def tick(self):
		#If no data can be found.
		if len(self.Services) == 0:
			if self.ticks == 0:
				self.image_composition.add_image(self.NoServices)

			#Wait a period of time then try getting new data again.
			if not self.is_waiting():
				self.top.delete()
				del self.top
				self.middel.delete()
				del self.middel
				self.bottom.delete()
				del self.bottom
				self.image_composition.remove_image(self.NoServices)
				self.State = "dead"
		else:
			# Tell all rows of the display next frame is wantted.
			self.top.tick()
			self.middel.tick()
			self.bottom.tick()
	
	# Called when a row has completed one cycle of it's states and requests to change card, here the program decides what to do.
	def requestCardChange(self, card, row):
		# If it has cycled through all cards, cycle from start again, unless enough time has passed for a new API request.
		if (self.x > Args.NumberOfCards or self.x >len(self.Services)-1):
			self.x = 1 if Args.FixToArrive else 0
			if LiveTime.TimePassed():  
				self.Services = LiveTime.GetData()
				print_safe("New Data Retrieved %s" % datetime.now().time())
		
		# If there are more rows (3) than there is services scheduled show nothing.
		if row > len(self.Services):       
			card.changeCard(LiveTimeStud(),device)
			return
		# If there is exactly 3 or less services the order in which they appear on the display is fixed to the order they will arrive in.
		if len(self.Services) <= 3:
			if self.Services[row-1].ID == card.CurrentService.ID:
				card.updateCard(self.Services[row-1],device)
			else:
				card.changeCard(self.Services[row-1],device)
		else:
			# If not they will cycled around showing whatever card is next.
			if Args.FixToArrive and row == 1:
				if self.Services[0].ID == card.CurrentService.ID:
					card.updateCard(self.Services[0],device)
				else:
					card.changeCard(self.Services[0],device)
			else:
				if self.Services[self.x % len(self.Services)].ID == card.CurrentService.ID:
					card.updateCard(self.Services[self.x % len(self.Services)],device)
				else:
					card.changeCard(self.Services[self.x % len(self.Services)],device)
		
		if  not (Args.FixToArrive and row == 1):
			self.x = self.x + 1

	# Used to add a time delay if there was an error with the last API request (providing a back off and wait mechanism)
	def is_waiting(self):
		self.ticks += 1
		if self.ticks > Args.RecoveryTime:
			self.ticks = 0
			return False
		return True
	

# Used to work out if the current time is between the inactive hours.
def is_time_between():
	# If check time is not given, default to current UTC time
	check_time = datetime.now().time()
	if Args.InactiveHours[0] < Args.InactiveHours[1]:
		return check_time >= Args.InactiveHours[0] and check_time <= Args.InactiveHours[1]
	else: # crosses midnight
		return check_time >= Args.InactiveHours[0] or check_time <= Args.InactiveHours[1]



# Checks that the user has allowed outputting to console.
def print_safe(msg):
	if not Args.NoConsole:
		print(msg)

###
## Main
## Connects to the display and makes it update forever until ended by the user with a ctrl-c
###
DisplayParser = cmdline.create_parser(description='Dynamically connect to either a vritual or physical display.')
device = cmdline.create_device( DisplayParser.parse_args(['--display', str(Args.Display),'--interface','spi','--width','256','--rotate',str(Args.Rotation),'--max-frames',str(Args.maxframes)]))


image_composition = ImageComposition(device)
board = boardFixed(image_composition,Args.Delay,device)
FontTime = ImageFont.truetype("%s/resources/time.otf" % (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))),16)
device.contrast(255)
energyMode = "normal"
StartUpDate = datetime.now().date()

# Draws the clock and tells the rest of the display next frame wanted.
def display():
	board.tick()
	msgTime = str(datetime.now().strftime("%H:%M" if (Args.TimeFormat==24) else "%I:%M"))	
	with canvas(device, background=image_composition()) as draw:
		image_composition.refresh()
		draw.multiline_text(((device.width - draw.textsize(msgTime, FontTime)[0])/2, device.height-16), msgTime, font=FontTime, align="center")

# Draws the splash screen on start up
def Splash():
	if Args.SplashScreen:
		with canvas(device) as draw:
			draw.multiline_text((64, 10), "Departure Board", font= ImageFont.truetype("%s/resources/Bold.ttf" % (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))),20), align="center")
			draw.multiline_text((45, 35), "Version : 2.0.EX -  By Jonathan Foot", font=ImageFont.truetype("%s/resources/Skinny.ttf" % (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))),15), align="center")
		time.sleep(5) #Wait such a long time to allow the device to startup and connect to a WIFI source first.

try:
	Splash()
	# Run the program forever		
	while True:
		time.sleep(0.02)

		if 'board' in globals() and board.State == "dead":
			del board
			board = boardFixed(image_composition,Args.Delay,device)
			device.clear()

		# Turns the display into one of the energy saving modes if in the correct time and enabled.
		if (Args.EnergySaverMode != "none" and is_time_between()):
			# Check for program updates and restart the pi every 'UpdateDays' Days.
			if (datetime.now().date() - StartUpDate).days >= Args.UpdateDays:
				print_safe("Checking for updates and then restarting Pi.")
				os.system("sudo git -C %s pull; sudo reboot" % (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))))
				sys.exit()
			if Args.EnergySaverMode == "dim":
				if energyMode == "normal":
					device.contrast(15)
					energyMode = "dim"
				display()
			elif Args.EnergySaverMode == "off":
				if energyMode == "normal":
					del board
					device.clear()
					device.hide()
					energyMode = "off"      
		else:
			if energyMode != "normal":
				device.contrast(255)
				if energyMode == "off":
					device.show()
					Splash()
					board = boardFixed(image_composition,Args.Delay,device)
				energyMode = "normal"
			display()
except KeyboardInterrupt:
	pass
