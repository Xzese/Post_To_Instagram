#!/usr/bin/env python3
import os
import requests
import dotenv
import datetime
import json
import random
import datetime
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

__all__ = ['post_random_photo']

dotenv.load_dotenv()

def add_to_log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = os.getenv('LOG_FILE')

    # Ensure parent directories exist
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    with open(log_file, 'a') as f:
        f.write(f'[{timestamp}] {message}\n')
    print(f'[{timestamp}] {message}\n')

def business_id_check():
    #get Business Account ID if missing
    if len(os.getenv('IG_BUSINESS_USER_ID')) == 0:
        endpoint_url = 'https://graph.facebook.com/v19.0/me/accounts'
        params = {
            'fields': 'instagram_business_account{id,username}',
            'access_token': os.getenv('ACCESS_TOKEN')
        }
        response = requests.get(endpoint_url, params=params)

        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # Parse the JSON response
            ig_business_account = response.json()
            os.environ['IG_BUSINESS_USER_ID'] = ig_business_account['data'][0]['instagram_business_account']['id']
            dotenv.set_key('.env',"IG_BUSINESS_USER_ID", os.environ["IG_BUSINESS_USER_ID"])
            return True
        else:
            add_to_log("Errorr Update User ID:" + response.text)
            return False

def upload_to_imgbb(image_path):
    if os.getenv('IMGBB_API_KEY') is not None and os.getenv('IMGBB_API_KEY') != '':

        with open(image_path, 'rb') as image_file:
            binary_data = image_file.read()
        
        endpoint_url = 'https://api.imgbb.com/1/upload'

        params = {
            'key': os.getenv('IMGBB_API_KEY'),
            'expiration':300
        }

        form_data = {
            'image': binary_data
        }
        # Send a GET request to the endpoint URL with the parameters
        response = requests.post(endpoint_url, params=params, files=form_data)
        
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            add_to_log("Uploaded image to imgbb: " + image_path)
            return response.json()['data']['image']['url']
        else:
            # raise the error message if the request was not successful
            error_message = f"Error Uploading Image: {response.text}"
            add_to_log(error_message)
            raise Exception(error_message)
    else:
        error_message = "No Valid IMGBB API Key"
        raise Exception(error_message)

def create_media_container(image_url, caption):
    if len(os.getenv('IG_BUSINESS_USER_ID')) == 0:
        if not business_id_check():
            add_to_log("No Valid Business ID")
            return
    if os.getenv('ACCESS_TOKEN') is not None and os.getenv('ACCESS_TOKEN') != '' and os.getenv('ACCESS_TOKEN_EXPIRY') is not None and os.getenv('ACCESS_TOKEN_EXPIRY') != '' and datetime.datetime.strptime(os.getenv('ACCESS_TOKEN_EXPIRY'), '%Y-%m-%d %H:%M:%S.%f') > datetime.datetime.now():
        endpoint_url = 'https://graph.facebook.com/v20.0/' + os.getenv('IG_BUSINESS_USER_ID') + '/media'
        params = {
            'image_url': image_url,
            'caption':caption,
            'access_token': os.getenv('ACCESS_TOKEN')
        }
        # Send a GET request to the endpoint URL with the parameters
        response = requests.post(endpoint_url, params=params)
        
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            add_to_log("Created media container: " + response.json()['id'])
            return response.json()['id']
        else:
            # raise the error message if the request was not successful
            error_message = f"Error Creating Media Container: {response.text}"
            add_to_log(error_message)
            raise Exception(error_message)
    else:
        return "No Valid Token"
    
def publish_media_container(creation_id):
    if len(os.getenv('IG_BUSINESS_USER_ID')) == 0:
        if not business_id_check():
            add_to_log("No Valid Business ID")
            return
    if os.getenv('ACCESS_TOKEN') is not None and os.getenv('ACCESS_TOKEN') != '' and os.getenv('ACCESS_TOKEN_EXPIRY') is not None and os.getenv('ACCESS_TOKEN_EXPIRY') != '' and datetime.datetime.strptime(os.getenv('ACCESS_TOKEN_EXPIRY'), '%Y-%m-%d %H:%M:%S.%f') > datetime.datetime.now():
        endpoint_url = 'https://graph.facebook.com/v20.0/' + os.getenv('IG_BUSINESS_USER_ID') + '/media_publish'
        params = {
            'creation_id': creation_id,
            'access_token': os.getenv('ACCESS_TOKEN')
        }
        # Send a GET request to the endpoint URL with the parameters
        response = requests.post(endpoint_url, params=params)
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            add_to_log("Published media container: " + creation_id)
            return response.json()
        else:
            # raise the error message if the request was not successful
            error_message = f"Error Publishing Media Container: {response.text}"
            add_to_log(error_message)
            raise Exception(error_message)
    else:
        error_message = "No Valid Facebook Token"
        add_to_log(error_message)
        raise Exception(error_message)

def post_random_photo(file_path, caption):
    if os.path.isfile(file_path):
        max_retries = 3
        attempt = 0
        while attempt < max_retries:
            try:
                upload_url = upload_to_imgbb(file_path)
                container_id = create_media_container(upload_url, caption)
                response = publish_media_container(container_id)
                if response == "No Valid Token" or response == None:
                    break
                add_to_log("Posted image ID: "+ file_path)
                break
            except Exception as e:
                attempt += 1
                add_to_log(f"Attempt {attempt} failed: {e}\nFile Path: {file_path}")
                if attempt == max_retries:
                    send_email_alert(
                        "[Instagram AI Image] Posting Failed",
                        f"The following error occurred after {max_retries} attempts: {e}\nFile Path: {file_path}"
                    )
    else:
        add_to_log("Image file path not valid: " + file_path)

def send_email_alert(subject, body):
    try:
        # Connect to SMTP server
        server = smtplib.SMTP(os.getenv('SMTP_SERVER'), os.getenv('SMTP_PORT'))
        server.starttls()
        server.login(os.getenv('SENDER_EMAIL'), os.getenv('SENDER_PASSWORD'))

        # Compose email message
        msg = MIMEMultipart()
        msg['From'] = os.getenv('SENDER_EMAIL')
        msg['To'] = os.getenv('RECIPIENT_EMAIL')
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Send email
        server.sendmail(os.getenv('SENDER_EMAIL'), os.getenv('RECIPIENT_EMAIL'), msg.as_string())

        # Close connection
        server.quit()

        add_to_log("Email alert sent with subject: " + subject)
    except Exception as e:
        add_to_log('Error sending email notification:', e)