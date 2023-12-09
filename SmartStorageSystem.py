'''
ECE 5725 Final Project: Smart Storage System
Team: Joash Shankar (jcs556), Ming He (hh759), Junze Zhou (jz2275)
Date: Dec 8th, 2023
SmartStorageSystem.py

Description: This system handles the logic like in a real apartment system. We handle facial recognition for valid/invalid users, april tag scanning for packages linked to users, email notifications sending to users, LEDs/sound to act as an indicator if the user is valid or not, and servos to open the bins.
'''

import RPi.GPIO as GPIO
import pygame
from pygame.locals import *
import textwrap
import time
import smtplib
from email.mime.text import MIMEText
import face_recognition
import imutils
from imutils.video import VideoStream
from imutils.video import FPS
import pickle
import cv2
import apriltag
from picamera.array import PiRGBArray
from picamera import PiCamera
import pigpio
import os

# GPIOs for servos: 5 6 13 19 20 21 26
# GPIOs for LEDs: 12 16
# Buttons used: 17 22 23 27

os.putenv('SDL_VIDEODRIVER', 'fbcon')
os.putenv('SDL_FBDEV', '/dev/fb0') # display on piTFT

pygame.init()
pygame.mouse.set_visible(False) # Turn on/off mouse cursor

pathUser = "/home/pi/detection.mp3"        # stores audio file corresponding to doorbell press (plays as face detection loads)
pathInvalid = "/home/pi/invalid_user.mp3"  # stores audio file corresponding to invalid user being scanned

# Mapping of april tag IDs to user information
tag_info = {
    1: "User: Joash",
    2: "User: Ming",
    3: "User: Bob", # used as a placeholder for demonstrating all bins are full so we don't overload servos assigned to Joash or Ming for the demo
    4: "",
    5: "",
    6: "",
    7: ""
    # 8: "",
    # 9: ""
    # Add more tags as needed
}

# Mapping of bin IDs to april tag IDs
# 3 is assigned to Bob for demo 
bin_AT = {
    1: 0,
    2: 3,
    3: 2,
    4: 3,
    5: 0, 
    6: 3, 
    7: 3
    # 8: 3,
    # 9: 3
}

# Mapping of bin numbers to GPIO pins
bin_to_gpio = {
    1: 13,
    2: 6,
    3: 5,
    4: 21,
    5: 26,
    6: 19,
    7: 20
    # 8: 20,
    # 9: 20  
}

# Keep track of bin status (open/close)
# bins 1 and 5 starts open and everything else closed for demo
bin_status = { 
    1: "open",
    2: "close",
    3: "close",
    4: "close",
    5: "open",
    6: "close",
    7: "close"
    # 8: "close",
    # 9: "close"
}

sys_start_time = time.time()
# Mapping of bin numbers to the time a package was placed in it
# (we hard coded this list for demo, to demonstrate when all bins are full) 
# time.time is used since we only use bin 1, 3, 5 for the demo. time.time is updating the package time so that
# whenever the system tries to find the older packages that are also out of valid time range, bins 2, 4, 6, 7 will be ignored.
# sys_start_time is used to properly indicate time, so that it can update the proper time when a package was dropped.
bin_package_time = {
    1: sys_start_time,
    2: time.time(),
    3: sys_start_time,
    4: time.time(),
    5: sys_start_time,
    6: time.time(),
    7: time.time()
    # 8: time.time(),
    # 9: time.time()
}

# Video stream object
vs = None

# Used for pygame init screen
screen = None

# Flags
pkg_Delivered = False           # track if package has been delivered
pkg_Picked = False              # track if package had been picked up
email_sent = False              # check if an email notif has been sent
AT_detect_start = False         # indicate start of april tag detection
out_time = False                # indicate if a timeout occurred during facial recognition         
delivery_man_detected = False   # indicate if a delivery person has been detected
invalid_user = False            # indicate unknown user
exit_flag = False               # indicate if the program needs to terminate
no_bin_avail = False            # indicate message that no bin is available

# Servo global variables
servos = {}                     # store servo objects for each bin
available = 500                 # servo pulse width to open a bin
unavailable = 1500              # servo pulse width to close a bin

# Other global variables
detect_cam_time_limit = 60      # time limit for facial recognition before timeout
bin_global = 0                  # keep track of current bin being accessed
tag_id = 0                      # store ID of a detected april tag
AT_info = ""                    # store info related to a detected april tag

# Find open bin to place user's package in
def find_open_bin():
    global bin_status
    global bin_AT 
    global bin_global
    global tag_id
    global bin_package_time
    global screen
    global tag_info
    global no_bin_avail
    # check if all bins are full
    all_bins_full = all(status == "close" for status in bin_status.values())

    if all_bins_full:
        curr_time = time.time() # get current time
        time_elapsed = {}

        # Loop through each bin to calculate the time elapsed since the last package was placed
        for bin_number, package_time in bin_package_time.items():
            if package_time is not None:
                time_elapsed[bin_number] = curr_time - package_time
            else:
                time_elapsed[bin_number] = 0

        # determine the bin to open based on the bin with most time elapsed
        bin_to_open = max(time_elapsed, key=time_elapsed.get) 
        
        # have bin open if the time elapsed is greater than 50 seconds
        if(time_elapsed[bin_to_open] > 50):
            display_message(screen, f"Take the previous package back to USPS. Bin {bin_to_open} will open for the new package. Press top-most button to close the bin!")
            expired_tag_id = bin_AT[bin_to_open]    # get tag ID of expired package
            expired_name = tag_info[expired_tag_id] # get name associated with tag ID

            # Determine user's expired package email
            if (expired_name == "User: Joash"):
                receiver_email = "jcs556@cornell.edu"
            elif (expired_name == "User: Ming"):
                receiver_email = "hh759@cornell.edu"
            elif (expired_name == "User: Bob"):
                receiver_email = "mingyedie@gmail.com"

            subject = "Package Expiration Alert"
            body = f"Dear {expired_name[6:]},\n\nYour time to pick up your package is up. Please pick it up at your closest USPS!\n\nSmart Storage System"
            open_bin(bin_to_open)
            time.sleep(0.2)
            send_email(subject, body, receiver_email)
        else:
            display_message(screen, "No bin is available.")
            no_bin_avail = True
            return
    else:
        # if not all bins are full, find the first available bin
        for bin_number, status in bin_status.items():
            if status == "open":
                bin_to_open = bin_number
                display_message(screen, "Hello Delivery Man, you may place the package in Bin " + str(bin_number) + " , then press the top-most button to close the bin.")
                break
    
    # Update the bin status, package time, and tag ID for the opened bin
    bin_status[bin_to_open] = "close"
    bin_package_time[bin_to_open] = time.time() # update the time when new package is placed
    bin_AT[bin_to_open] = tag_id
    bin_global = bin_to_open

# Handle bin with user's package when picked up
def get_package(user_name):
    global tag_info
    global bin_AT
    global bin_status
    global screen

    bin_pkgs = []                                                                # store bin number with user's package
    tag_id_for_pkg = [k for k, v in tag_info.items() if v[6:] == user_name][0]   # get april tag id associated with user

    # Find bin containing user's package
    for k, v in bin_AT.items():
        if v == tag_id_for_pkg:
            bin_pkgs.append(k) # store bin number when match is found

    # Logic to handle picking up package
    if bin_pkgs:
        if (len(bin_pkgs) > 1): # if user has packages in more than one bin
            many_bins_str = ', '.join(map(str, bin_pkgs)) # concat bin numbers into a string
            display_message(screen, "Hey " + user_name + ", you may collect your packages in bins "+many_bins_str+"!")
        else: # if user has package in one bin
            display_message(screen, "Hey " + user_name + ", you may collect your package at bin "+str(bin_pkgs[0])+"!")

        for bin_number in bin_pkgs: # open each bin containing the user's packages and update their status
            open_bin(bin_number)
            bin_status[bin_number] = "open" # reset bin status after package picked up
            bin_AT[bin_number] = 0          # reset bin_AT to indicate no package associated with bin
    else:
        display_message(screen, "Hey " + user_name + ", you have no packages.")

# Initialize servos
def initialize_servos():
    global servos
    global bin_to_gpio

    for bin_number, pin in bin_to_gpio.items(): # iterate through each bin and its corresponding GPIO pin
        servos[bin_number] = pigpio.pi()                # init pigpio object for each bin
        servos[bin_number].set_mode(pin, pigpio.OUTPUT) # set GPIO pin as an output
        close_bin(bin_number)                            
        time.sleep(0.1)                                 # short delay to ensure servo is stable
    
    # used for demo
    # open_bin(1)
    # time.sleep(0.1)
    # open_bin(5)
    # time.sleep(0.1)

# Stop servos
def stop_servos():
    global servos
    global bin_to_gpio

    for bin_number, pin in bin_to_gpio.items(): # iterate through each bin
        servos[bin_number].stop()               # stop servo associated with bin
        time.sleep(0.1)                         # short delay to ensure servo is stable

# Open bin (turn servo 90 degrees)
def open_bin(bin_number):
    global servos
    global bin_to_gpio

    pin = bin_to_gpio[bin_number]                           # get GPIO associated with bin number
    servos[bin_number].set_servo_pulsewidth(pin, available) # set servo pulse width to open bin (500)

# Close bin (turn servo 0 degrees)
def close_bin(bin_number):
    global servos
    global bin_to_gpio

    pin = bin_to_gpio[bin_number]                             # get GPIO associated with bin number
    servos[bin_number].set_servo_pulsewidth(pin, unavailable) # set servo pulse width to close bin (1500)

# User/Delivery Man doorbell button
def GPIO27_callback(channel):
    global screen

    display_message(screen, "User detected. Processing face recognition...")
    pygame.mixer.music.load(pathUser)        # load audio file
    pygame.mixer.music.play(loops=1)         # play audio file
    if not pygame.mixer.music.get_busy():    # wait until audio is done playing
        pygame.mixer.music.unload()
    process_face_detection(user=True)        # start face recognition

# Delivery Man button to indicate they placed package in bin
def close_bin_after_pkg(): # GPIO17
    global bin_global
    global delivery_man_detected

    close_bin(bin_global)
    delivery_man_detected = False # reset flag
    #cv2.destroyAllWindows()

# April tag detection
def AprilTag_scan():
    global vs
    global AT_info
    global AT_detect_start
    global screen
    global out_time        
    global bin_global
    global delivery_man_detected
    global detect_cam_time_limit
    global tag_id
    
    temp_count = 0
    temp_bool = True
    start_time_AT = time.time()

    display_message(screen, "Scanning for AprilTag...")

    while True:
        if temp_bool:
            frame = vs.read()

            # Initialize AprilTag detector with a tag family
            options = apriltag.DetectorOptions(families='tag16h5')
            detector = apriltag.Detector(options)

            # Convert to grayscale for detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Detect AprilTags in the image
            results = detector.detect(gray)

            for r in results:
                # Draw the bounding boxes around the detected april tag
                (ptA, ptB, ptC, ptD) = r.corners
                for i in range(4):
                    pt1 = (int(r.corners[i][0]), int(r.corners[i][1]))
                    pt2 = (int(r.corners[(i + 1) % 4][0]), int(r.corners[(i + 1) % 4][1]))
                    cv2.line(frame, pt1, pt2, (0, 255, 0), 2)

                # Retrieve information based on the tag ID
                tag_id = r.tag_id 
                AT_info = tag_info.get(tag_id, "Unknown Tag")

            # Show the output frame - uncomment if you want to see bounding box of facial detection live on monitor
            # cv2.imshow("AprilTag Scan", frame)
            # key = cv2.waitKey(1) & 0xFF
            
            # camera recognition timeout check
            if (time.time() - start_time_AT > detect_cam_time_limit):
                display_message(screen, "Timing out... No AprilTag detected!")
                out_time = True
                break

            # Check if user's associated april tag is detected and open bin for user
            if ("User:" in AT_info):
                find_open_bin()
                temp_bool = False
                # cv2.destroyAllWindows()
                if no_bin_avail == True:
                    break
                    
        else:
            if (not GPIO.input(17)):
                if bin_global != 0:
                    time.sleep(0.2)
                    display_message(screen, f"Bin {bin_global} is closing!")
                    close_bin_after_pkg()
                    break
            time.sleep(0.1)
            
            if delivery_man_detected and bin_global != 0 and time.time() - start_time_AT  > 30: # close a bin if delivery man is detected and specific bin was open after a period of time
                display_message(screen, f"Bin {bin_global} is closing!")
                close_bin(bin_global)
                bin_package_time[bin_global] = time.time()
                delivery_man_detected = False # reset flag
                break

# Face detection
def process_face_detection(user):
    global vs
    global pkg_Delivered
    global pkg_Picked
    global AT_detect_start
    global email_sent
    global AT_info
    global screen
    global led
    global delivery_man_detected
    global invalid_user
    global out_time
    global detect_cam_time_limit

    # At the start of face recognition
    display_message(screen, "Scanning in progress, please stand by...")

    start_time = time.time()

    # Load face encodings and initialize the video stream
    data = pickle.loads(open("/home/pi/SmartStorageSystem/encodings.pickle", "rb").read())

    # Start the FPS counter
    fps = FPS().start()

    # Capture and process frames in a loop
    while True:
        frame = vs.read()
        frame = imutils.resize(frame, width=500)
        boxes = face_recognition.face_locations(frame)
        encodings = face_recognition.face_encodings(frame, boxes)
        names = []
        name = ""

        # Loop over the facial embeddings
        for encoding in encodings:
            matches = face_recognition.compare_faces(data["encodings"], encoding)
            name = "Unknown"  # if face is not recognized

            # Check to see if we have found a match
            if True in matches:
                # Find the indexes of all matched faces then init a dict to count each face
                matchedIdxs = [i for (i, b) in enumerate(matches) if b]
                counts = {}

                # Count each recognized face
                for i in matchedIdxs:
                    name = data["names"][i]
                    counts[name] = counts.get(name, 0) + 1

                # Determine the recognized face with the largest number of votes
                name = max(counts, key=counts.get)

                receiver_email = ""
                subject = ""
                body = ""

                # Action based on the person's identity
                if user and (name == "Joash" or name == "Ming"):
                    # User recognized, open the user's bin
                    email_sent = True
                    GPIO.output(12, GPIO.HIGH)
                    get_package(name)
                    time.sleep(3)
                elif user and name == "Delivery Man":
                    AT_detect_start = True
                    GPIO.output(12, GPIO.HIGH)
                    delivery_man_detected = True

            else:
                # Access denied / unrecognized person
                GPIO.output(16, GPIO.HIGH)
                pygame.mixer.music.load(pathInvalid)        # load audio file
                pygame.mixer.music.play(loops=1)            # play audio file
                if not pygame.mixer.music.get_busy():       # wait until audio is done playing
                    pygame.mixer.music.unload()
                
                display_message(screen, "Access denied. Unrecognized user.")
                time.sleep(2)
            
            # update the list of names
            names.append(name)
            
        # loop over the recognized faces
        for ((top, right, bottom, left), name) in zip(boxes, names):
            # draw the predicted face name on the image - color is in BGR
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 225), 2)
            y = top - 15 if top - 15 > 15 else top + 15
            cv2.putText(frame, name, (left, y), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 255, 255), 2)

        # display the image to our monitor - uncomment if you want to see bounding box of facial detection live on monitor
        # cv2.imshow("Facial Recognition is Running", frame)
        # key = cv2.waitKey(1) & 0xFF

        # camera recognition timeout check
        if (time.time() - start_time  > detect_cam_time_limit):
            display_message(screen, "Timing out... No user detected!")
            out_time = True
            break
        
        if (name == "Unknown"):
            invalid_user = True
            break            
        
        if (email_sent == True):
            # sending an email
            if name == "Joash":
                receiver_email = "jcs556@cornell.edu"
            elif name == "Ming":
                receiver_email = "hh759@cornell.edu"
            elif name == "Bob":
                receiver_email = "mingyedie@gmail.com"
            
            subject = "Package Picked Up Alert"
            body = f"Dear {name},\n\nyou've picked up your package!\n\nSmart Storage System"
            
            display_message(screen, f"Email notification sent to {name}.")
            send_email(subject, body, receiver_email)
            pkg_Picked = True
            break

        if AT_detect_start == True:
            AprilTag_scan()

            # send email to respective user after apriltag is scanned
            if (AT_info == "User: Joash"):
                receiver_email = "jcs556@cornell.edu"
            elif (AT_info == "User: Ming"):
                receiver_email = "hh759@cornell.edu"
            elif (AT_info == "User: Bob"):
                receiver_email = "mingyedie@gmail.com"

            subject = "Package Delivery Alert"
            body = f"Dear {AT_info[6:]},\n\nYour package has been delivered!\n\nSmart Storage System"
            send_email(subject, body, receiver_email)
            pkg_Delivered = True
            break

        # quit when 'q' key is pressed
        # if key == ord("q"):
        #    break

        # update the FPS counter
        fps.update()
    
    # stop the timer and display FPS information
    fps.stop()

    # cv2.destroyAllWindows()

# Send email to users
def send_email(subject, body, receiver_email):
    # Set up the SMTP server and port
    smtp_server = 'smtp.gmail.com'
    port = 587

    # Sender and receiver email addresses
    sender_email = 'jzz712846@gmail.com'

    # Email credentials
    password = 'iyzh pctt gqwa drmj'

    # Create a MIMEText object to represent the email
    message = MIMEText(body)
    message['From'] = sender_email
    message['To'] = receiver_email
    message['Subject'] = subject

    # Start the SMTP session
    server = smtplib.SMTP(smtp_server, port)
    server.starttls() # Start TLS encryption
    server.login(sender_email, password) # Log in to the SMTP server

    # Send the email
    server.sendmail(sender_email, receiver_email, message.as_string())

    # Close the SMTP session
    server.quit()

# Initializes and returns the main display surface
def init_pygame_display():
    pygame.display.init()
    size = (320, 240)
    screen_init = pygame.display.set_mode(size)  # create window of specified size 
    return screen_init

# Displays message on Pygame surface (wraps and centers text)
def display_message(screen, message, font_size=28, color=(255, 255, 255)):
    screen.fill((0, 0, 0))  # clear screen
    pygame.display.update()

    font = pygame.font.Font(None, font_size)

    # Wrap the text
    wrapped_text = textwrap.wrap(message, width=30)

    # Starting Y position
    start_y = (240 - (font_size * len(wrapped_text))) // 2  # center the block of text vertically

    # Render and display each line of text
    for i, line in enumerate(wrapped_text):
        text_surface = font.render(line, True, color)
        rect = text_surface.get_rect(center=(160, start_y + i * font_size))
        screen.blit(text_surface, rect)

    pygame.display.update() # show text

# Used as a failsafe quit
def GPIO22_callback(channel):
    global exit_flag
    exit_flag = True
    
# Used as a shutdown button
def GPIO23_callback(channel):
    global screen
    display_message(screen, "Shutting down the system. Have a great day!")
    time.sleep(2)
    os.system('sudo shutdown -h now')

# Resets the system to its initial state by modifying global variables and resetting LED
def system_reset(init = False):
    global pkg_Delivered 
    global pkg_Picked 
    global AT_info
    global email_sent 
    global AT_detect_start
    global out_time 
    global led
    global screen
    global vs
    global invalid_user
    global bin_global
    
    if (not init):
        pkg_Delivered = False
        pkg_Picked = False
        AT_info = ""
        email_sent = False
        AT_detect_start = False
        out_time = False
        invalid_user = False
        bin_global = 0

    display_message(screen, "Welcome to the Smart Storage System. Click on the doorbell (bottom-most button) if you're a valid user.")
    
    # reset LEDs
    GPIO.output(16, GPIO.LOW)
    GPIO.output(12, GPIO.LOW)

# Main loop
def main():
    # Display initial message 
    global screen
    global vs
    global pkg_Delivered
    global led
    global exit_flag
    global pkg_Picked
    global out_time
    global invalid_user

    # init pygame font and show welcome message
    pygame.font.init()
    screen = init_pygame_display()
    display_message(screen, "Welcome to the Smart Storage System. Click on the doorbell (bottom-most button) if you're a valid user.")

    exit_flag = False
    initialize_servos()

    # GPIO setup
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP) # push button
    GPIO.setup(27, GPIO.IN, pull_up_down=GPIO.PUD_UP) # push button
    GPIO.add_event_detect(27, GPIO.FALLING, callback=GPIO27_callback, bouncetime=300)
    GPIO.setup(22, GPIO.IN, pull_up_down=GPIO.PUD_UP) # push button
    GPIO.add_event_detect(22, GPIO.FALLING, callback=GPIO22_callback, bouncetime=300)
    GPIO.setup(23, GPIO.IN, pull_up_down=GPIO.PUD_UP) # push button
    GPIO.add_event_detect(23, GPIO.FALLING, callback=GPIO23_callback, bouncetime=300)
    
    # Pygame setup for sound
    pygame.mixer.init()
    
    # Initialize the video stream here and let it warm up
    vs = VideoStream(usePiCamera=True, resolution = (640, 480), framerate = 32).start()
    time.sleep(2.0)
    
    # LEDs setup
    GPIO.setup(16, GPIO.OUT) 
    GPIO.setup(12, GPIO.OUT) 
    GPIO.output(16, GPIO.LOW)
    GPIO.output(12, GPIO.LOW)
    
    system_reset(True)
    
    # Main loop to keep the program running
    while not exit_flag:
        if (pkg_Delivered or pkg_Picked or out_time or invalid_user):
            system_reset()
        time.sleep(0.5)

    GPIO.cleanup()
    pygame.mixer.quit()
    stop_servos()
    vs.stop()

    display_message(screen, "Quitting the system...")
    time.sleep(1)

if __name__ == "__main__":
    main()