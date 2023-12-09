'''
ECE 5725 Final Project: Smart Storage System
Team: Joash Shankar (jcs556), Ming He (hh759), Junze Zhou (jz2275)
Date: Dec 8th, 2023
headshots_picam.py

Description: Capture images from RPi camera and save them to a dataset directory, which signifies known users.
'''

import cv2
from picamera import PiCamera
from picamera.array import PiRGBArray

name = 'Name' # replace with name of user you want to add

cam = PiCamera()
cam.resolution = (512, 304)
cam.framerate = 10 
rawCapture = PiRGBArray(cam, size=(512, 304))
    
img_counter = 0

while True:
    for frame in cam.capture_continuous(rawCapture, format="bgr", use_video_port=True):
        image = frame.array
        cv2.imshow("Press Space to take a photo", image)
        rawCapture.truncate(0)
    
        k = cv2.waitKey(1)
        rawCapture.truncate(0)
        if k%256 == 27: # ESC pressed
            break
        elif k%256 == 32: # SPACE pressed
            img_name = "dataset/"+ name +"/image_{}.jpg".format(img_counter) # add taken img to dataset folder matching the already-created name of the user
            cv2.imwrite(img_name, image)
            print("{} written!".format(img_name))
            img_counter += 1 # incrementing so you can take multiple images of user
            
    if k%256 == 27: # ESC pressed
        print("Escape hit, closing...")
        break

cv2.destroyAllWindows()