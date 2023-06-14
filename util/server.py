"""Code to programatically update ArcGIS sandbox server"""

# https://community.esri.com/thread/186020-start-stop-map-service-arcpy
# Demonstrates how to stop or start all services in a folder

import sys
import common
import log
import logging

# For Http calls
import urllib
import urllib.parse
import json
import requests

# avoid proxy issues
VERIFY = False
## Connection credentials for ArcGIS server
USERNAME = common.CONFIG.get('gis', 'username')
PASSWORD = common.CONFIG.get('gis', 'password')
SERVER = common.CONFIG.get('gis', 'server')
# want to use settings so we aren't going into other folders
FOLDER = common.CONFIG.get('gis', 'folder').strip('/')
assert FOLDER


def assertJsonSuccess(data):
    """A function that checks that the input JSON object is not an error object."""
    obj = json.loads(data)
    if 'status' in obj and obj['status'] == "error":
        logging.error(f"Error: JSON object returns an error. {obj}")
        return False
    else:
        return True


def getToken():
    """A function to generate a token given username, password and the adminURL."""
    # Token URL is typically http://server[:port]/arcgis/admin/generateToken
    headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
    tokenURL = f"{SERVER}/arcgis/admin/generateToken?client=requestip&f=json"
    params = {
        'username': USERNAME,
        'password': PASSWORD
        }
    # Connect to URL and post parameters
    response = requests.post(tokenURL, data=params, verify=VERIFY, headers=headers)
    if (response.status_code != 200):
        logging.error("Error while fetching tokens from admin URL. Please check the URL and try again.")
        return
    else:
        data = response.content
        # Check that data returned is not an error object
        if not assertJsonSuccess(data):
            return
        # Extract the token from it
        token = json.loads(data)
        return token['token']


## Dictionary of services by folder that they are in
SERVICES_BY_FOLDER = {}

def startOrStopServices(stopOrStart, folder=FOLDER, whichServices=None):
    """Start or stop services"""
    logging.info(f"Calling {stopOrStart} on {folder} for services {whichServices}")
    # Check to make sure stop/start parameter is a valid value
    if str.upper(stopOrStart) != "START" and str.upper(stopOrStart) != "STOP":
        logging.error("Invalid STOP/START parameter entered")
        return
    assert folder.strip('/')
    # Get a token
    token = getToken()
    if token == "":
        logging.error("Could not generate a token with the username and password provided.")
        return
    # Construct URL to read folder
    folderURL = f"{SERVER}/arcgis/admin/services/{folder}"
    # This request only needs the token and the response formatting parameter
    params = {'token': token, 'f': 'json'}
    headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
    if folder not in SERVICES_BY_FOLDER:
        response = requests.post(folderURL, data=params, verify=VERIFY, headers=headers)
        if (response.status_code != 200):
            logging.error("Could not read folder information.")
            return
        data = response.content
        # Check that data returned is not an error object
        if not assertJsonSuccess(data):
            logging.error(f"Error when reading folder information. {data}")
            return
        services = []
        # Deserialize response into Python object
        dataObj = json.loads(data)
        # Loop through each service in the folder and stop or start it
        for item in dataObj['services']:
            fullSvcName = item['serviceName'] + "." + item['type']
            services.append(fullSvcName)
        SERVICES_BY_FOLDER[folder] = services
    services = SERVICES_BY_FOLDER[folder]
    if not whichServices:
        # do everything if nothing specified
        whichServices = services
    if str == type(whichServices):
        # special case a single item to make it a list
        whichServices = [whichServices]
    bad_service = False
    for service in whichServices:
        if service not in services:
            logging.error(f"Invalid service requested: {service}")
            bad_service = True
    if bad_service:
        return
    for fullSvcName in whichServices:
        # Construct URL to stop or start service, then make the request
        stopOrStartURL = f"{SERVER}/arcgis/admin/services/{folder}/{fullSvcName}/{stopOrStart}"
        stopStartResponse = requests.post(stopOrStartURL, data=params, verify=VERIFY, headers=headers)
        if (stopStartResponse.status_code != 200):
            logging.error("Error while executing stop or start. Please check the URL and try again.")
            return
        else:
            stopStartData = stopStartResponse.content
            # Check that data returned is not an error object
            if not assertJsonSuccess(stopStartData):
                if str.upper(stopOrStart) == "START":
                    logging.error(f"Error returned when starting service {fullSvcName}.")
                else:
                    logging.error("Error returned when stopping service {fullSvcName}.")
            else:
                logging.info(f"Service {fullSvcName} processed {stopOrStart} successfully.")


def stopServices(folder=FOLDER, whichServices=None):
    """Stop servies"""
    startOrStopServices('STOP', folder, whichServices)


def restartServices(folder=FOLDER, whichServices=None):
    """Stop and then start services"""
    startOrStopServices('STOP', folder, whichServices)
    startOrStopServices('START', folder, whichServices)

def startServices(folder=FOLDER, whichServices=None):
    """Start services"""
    startOrStopServices('START', folder, whichServices)

