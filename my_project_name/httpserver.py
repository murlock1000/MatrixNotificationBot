#!/usr/bin/env python3
"""
A HTTP server for listening to POST requests and relaying the messages to a Matrix bot.
Usage::
    POST request:
    write message as plain text format 
    or
    use form-data with key: "Message"
    ./server.py [<port>]

Ubuntu usage::
curl -k -X POST -H "Content-Type: text/plain" --data "${NotificationMessage}" https://localhost:8080

create ssl certificate:
openssl req -new -x509 -keyout server.pem -out server.pem -days 365 -nodes
"""
import asyncio
from re import T
import time
from threading import Thread
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import ssl
import sys

logger = logging.getLogger(__name__)

async def sample_callback(msg):
    #await asyncio.sleep(3)
    print(f"Relaying: {msg}")

MESSAGE_CALLBACK = sample_callback
API_KEY = "apiKey"
EVENT_LOOP = None

class httpRequestHandler(BaseHTTPRequestHandler):
    def _set_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    # Define Post request response
    def do_POST(self):
        content_length = int(self.headers['Content-Length']) # <--- Gets the size of data
        post_data = self.rfile.read(content_length) # <--- Gets the data itself
        logger.debug(f"POST request, data: {post_data}")
       # print("POST request,\nPath: %s\nHeaders:\n%s\n\nBody:\n%s\n",
      #          str(self.path), str(self.headers), post_data.decode('utf-8'))
      #  print("###########################\n")

        contentType = str(self.headers.get("Content-Type")).split(';') # <--- get type of post request body
        api_key = str(self.headers.get("Api-Key-Here")).split(';')[0]  # <--- get api key

        post_data.decode('utf-8') # convert post body data into string
        self._set_response() #initiate response
        # We will parse POST requests with body formats of multipart/form-data with name="Message" or text/plain sending everything.
        if api_key == API_KEY:
            if contentType[0] == "multipart/form-data":
                boundary = contentType[1].split('=') # parse multipart/form-data boundary string
                msg = self.parsePostData(post_data.decode('utf-8'),boundary[1]) #parse post request data manually
                self.initiate_callback(msg) # initiate callback
            elif contentType[0]=="text/plain":
                msg = post_data.decode('utf-8')
                self.initiate_callback(msg) # initiate callback

    def initiate_callback(self, msg):
        if msg!="":
            self.wfile.write("POST request for {} was Successfull!".format(self.path).encode('utf-8'))
            logger.debug(f"Calling callback with message: {msg}")
            EVENT_LOOP.create_task(MESSAGE_CALLBACK(msg)) # Send the message to all subscribed chat groups
        else:
            self.wfile.write("POST request data was empty or the text/plain data was wrong.".encode('utf-8'))
                
    def parsePostData(self, data, boundary):
        data = str(data).split("--"+boundary+'\r\n')[1:] # Separate body data into fields with string manipulation.
        for i in range(len(data)):
            # Find field name
            start = data[i].find('name="')+6
            end = data[i][start+6:].find('"')+6
            name = data[i][start:end+start]
            # Get text content of the field
            body = data[i][end+start+5:]
            # Clean up text of remaining boundary strings
            body = body.replace("\r\n--"+boundary+"--","")
            # if field name matches key return the text content
            if name=="Message":
                return body[:-2]
        return ""

class HttpServerInstance():
    def __init__(self, loop, port=8080):
        global EVENT_LOOP
        EVENT_LOOP = loop
        self.port = port

    def runHttpServer(self, httpd):
        try:
            httpd.serve_forever()
        except:
            pass


    def run(self):
        server_address = ('', self.port) 
        # Create a http server instance and run it in a separate thread.
        self.httpd = HTTPServer(server_address, httpRequestHandler)
        #setting up ssl sertification
        self.httpd.socket = ssl.wrap_socket (self.httpd.socket, certfile='./server.pem', server_side=True)
        logger.info('Starting httpd...')
        try:
            self.thread = Thread(target= self.runHttpServer, args=(self.httpd,))
            self.thread.start()
        except KeyboardInterrupt: # On Exit we close the http server.
            logger.warning("Received keyboard interrupt, stopping.")
            self.stop()

    def stop(self):
        logger.info('Stopping httpd...')
        self.httpd.server_close()
        logger.info("HTTPD Server stopped.")
        self.thread.join() # does not stop??
        logger.info("thread joined")
    
    def set_callback(self, callback):
        global MESSAGE_CALLBACK
        MESSAGE_CALLBACK = callback
    
    def set_api_key(self, key):
        global API_KEY
        API_KEY = key
    
async def mainLoop():
    while(True):
        try:
            await asyncio.sleep(1)
        except KeyboardInterrupt: # On Exit we close the http server.
            logger.warning("Received keyboard interrupt, stopping.")
            break

if __name__ == '__main__':
    from sys import argv
    EVENT_LOOP
    EVENT_LOOP = asyncio.get_event_loop()
    if len(argv) == 2:
        httpServerInstance = HttpServerInstance(int(argv[1]))
         # Set a custom port ex: ./server.py 5665
    else:
        httpServerInstance = HttpServerInstance()
    httpServerInstance.run()
    EVENT_LOOP.run_until_complete(mainLoop())
