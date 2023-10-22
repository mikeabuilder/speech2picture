"""
This program generates photos from random audio conversations and displays 
them on the screen. When run on command, it is an interesting exercise in the power of OpenAI.
When run in continuous mode, it is a creepy photo generator because it shows how good openAI is 
at understanding what you are saying.

There is a step that is now commented out that summarizes the transcript. The summary is 
errily accurate.

Basic flow:
    * record audio from the default microphone and then transcribe it using OpenAI
    * summarize the transcript and generate 4 pictures based on the summary
    * combine the four images into a single image
    * open the picture in a browser
    * optionally, delay for 60 seconds and repeat the process
    * images are stored in the history directory

The program can be run in two modes:
    
1/  python3 pyspeech.py
    This will display a menu and prompt you for a command. 
2/  python3 pyspeech.py -h
    For testing. Use command line arguments  

control-c to stop the program. When run in auto mode it will loop 10 times

For debug output, use the -d 2 argument. This will show the prompts and responses to/from OpenAI.

To run this you need to get an OpenAI API key and put it in a file called "creepy photo secret key".
OpenAI currently costs a few pennies to use. I've run this for an hour at a cost of $1.00. It was
well worth it.

Based on the WhisperFrame project idea on Hackaday.
https://hackaday.com/2023/09/22/whisperframe-depicts-the-art-of-conversation/

Specific to Raspberry Pi:
    1. set up a virtual environment and activate it (to deactive use "deactivate")
    python3 -m venv .venv
    source .venv/bin/activate
    python3 -m pip install -r requirements.txt

    
    2. install the following packages
    sudo apt-get install libasound2-dev
    sudo apt-get install portaudio19-dev
    sudo apt-get install libatlas-base-dev
    sudo apt-get install libopenblas-dev

    3. install the following python packages    
    pip install openai
    pip install pillow
    pip install pyaudio

    Note that when run you will see 10 or so lines of errors about sockets and JACKD and whatnot.
    Don't worry, it is still working. If you know how to fix this, please let me know.

    Also note that errors from the audio subsystem are ignored in recordAudioFromMicrophone(). If 
    you are having some real audio issue, you might change the error handler to print the errors.
    
Author: Jim Schrempp 2023 
"""

# import common libraries
import platform
import argparse
import logging
import webbrowser
import urllib.request
import time
import shutil
import re
import os
import openai
import ssl
#import numpy
from enum import IntEnum
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__) # parameter: -d 1
loggerTrace = logging.getLogger("Prompts") # parameter: -d 2

# import platform specific libraries
g_isMacOS = False
if (platform.system() == "Darwin"):
    g_isMacOS = True
else:
    print ("Not MacOS")

if g_isMacOS:
    import sounddevice
    import soundfile

else:
    # --------- set for Raspberry Pi -----------------------------------------
    import pyaudio
    import wave
    from ctypes import *
    import RPi.GPIO as GPIO
    import threading
    from queue import Queue




# Set the duration of each recording in seconds
duration = 60

# Set the number of times to loop when in auto mode
loopsMax = 10

# Prompt for abstraction
promptForAbstraction = "What is the most interesting concept in the following text \
    expressing the answer as a noun phrase, but not in a full sentence "

# image modifiers
imageModifiersArtist = [
                    " in the style of Picasso",
                    " in the style of Van Gogh",
                    " in the style of Monet",
                    " in the style of Dali",
                    " in the style of Escher",
                    " in the style of Rembrandt",
                    ]
imageModifiersMedium = [
                    " as a painting",
                    " as a watercolor",
                    " as a sketch",
                    " as a drawing",
                    " as a sculpture",
                    " as a photograph",
                    ]



if not g_isMacOS:
    # --------- Raspberry Pi specific code -----------------------------------------
    logger.info("Setting up GPIO pins")
    # Set the pin numbering mode to BCM
    GPIO.setmode(GPIO.BOARD)

    # Set up pin 8 as an output
    GPIO.setup(8, GPIO.OUT, initial=GPIO.LOW)

    # Define some constants for blinking the LED (onTime, offTime)
    constBlinkFast = (0.1, 0.1)
    constBlinkSlow = (0.5, 0.5)
    constBlinkAudioCapture = (0.05, 0.05)
    constBlink1 = (0.5, 0.2)
    constBlink2 = (0.4, 0.2)
    constBlink3 = (0.3, 0.2)
    constBlink4 = (0.2, 0.2)

    constBlinkStop = (-1, -1)
    constBlinkDie = (-2, -2)

    # Define a function to blink the LED
    # This function is run on a thread
    # Communicate by putting a tuple of (onTime, offTime) in the qBlinkControl queue
    #
    def blink_led(q):
        print("Starting LED thread") # why do I need to have this for the thread to work?
        logger.info("logging, Starting LED thread")

        # initialize the LED
        isBlinking = False
        GPIO.output(8, GPIO.LOW)

        while True:
            # Get the blink time from the queue
            try:
                blink_time = q.get_nowait()
            except:
                blink_time = None

            if blink_time is None:
                # no change
                pass
            elif blink_time[0] == -2:
                # die
                logger.info("LED thread dying")
                break
            elif blink_time[0] == -1:
                # stop blinking
                GPIO.output(8, GPIO.LOW)
                isBlinking = False
            else:
                onTime = blink_time[0]
                offTime = blink_time[1]
                isBlinking = True

            if isBlinking:
                # Turn the LED on
                GPIO.output(8, GPIO.HIGH)
                # Wait for blink_time seconds
                time.sleep(onTime)
                # Turn the LED off
                GPIO.output(8, GPIO.LOW)
                # Wait for blink_time seconds
                time.sleep(offTime)

    # Create a new thread to blink the LED
    logger.info("Creating LED thread")
    qBlinkControl = Queue()
    led_thread1 = threading.Thread(target=blink_led, args=(qBlinkControl,),daemon=True)
    led_thread1.start()


    # --------- end of Raspberry Pi specific code ----------------------------


                                
# ----------------------
# record duration seconds of audio from the default microphone to a file and return the sound file name
#
def recordAudioFromMicrophone():

    soundFileName = 'recording.wav'
    
    # delete file recording.wav if it exists
    try:
        os.remove(soundFileName)
    except:
        pass # do nothing   
    
    if g_isMacOS:
        # print the devices
        # print(sd.query_devices())  # in case you have trouble with the devices

        # Set the sample rate and number of channels for the recording
        sample_rate = int(sounddevice.query_devices(1)['default_samplerate'])
        channels = 1

        logger.debug('sample_rate: %d; channels: %d', sample_rate, channels)

        logger.info("Recording %d seconds...", duration)
        os.system('say "Recording."')
        # Record audio from the default microphone
        recording = sounddevice.rec(
            int(duration * sample_rate), 
            samplerate=sample_rate, 
            channels=channels
            )

        # Wait for the recording to finish
        sounddevice.wait()

        # Save the recording to a WAV file
        soundfile.write(soundFileName, recording, sample_rate)

        os.system('say "Thank you. I am now analyzing."')

    else:

        # RPi
        """
        recording = sounddevice.Stream(channels=1, samplerate=44100)
        recording.start()
        time.sleep(15)
        recording.stop()
        soundfile.write('test1.wav',recording, 44100)
        """

        # all this crap because the ALSA library can't police itself
        ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
        def py_error_handler(filename, line, function, err, fmt):
            pass #nothing to see here
        c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
        asound = cdll.LoadLibrary('libasound.so')
        # Set error handler
        asound.snd_lib_error_set_handler(c_error_handler)
        # Initialize PyAudio
        pa = pyaudio.PyAudio()
        # Reset to default error handler
        asound.snd_lib_error_set_handler(None)
        # now on with the show, sheesh

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=44100,
            input=True,
            frames_per_buffer=1024
            ) #,input_device_index=2)

        wf = wave.open(soundFileName,"wb")
        wf.setnchannels(1)
        wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(44100)

        # Write the audio data to the file
        for i in range(0, int(44100/1024*10)):

            # Get the audio data from the microphone
            data = stream.read(1024)

            # Write the audio data to the file
            wf.writeframes(data)

        # Close the microphone and the wave file
        stream.close()
        wf.close()

    return soundFileName

# ----------------------
# transcribe the audio file and return the transcript
#
def getTranscript(wavFileName):

    # transcribe the recording
    # Note: you need to be using OpenAI Python v0.27.0 for the code below to work
    logger.info("Transcribing...")
    audio_file= open(wavFileName, "rb")
    responseTranscript = openai.Audio.transcribe("whisper-1", audio_file)

    # print the transcript
    loggerTrace.debug("Transcript: " + str(responseTranscript))

    # get the text from the transcript
    transcript = responseTranscript["text"]     

    return transcript

# ----------------------
# summarize the transcript and return the summary
#
def getSummary(textInput):
    
    # summarize the transcript 
    logger.info("Summarizing...")

    responseSummary = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content" : 
            f"Please summarize the following text:\n{textInput}" }
        ]               
    )
    loggerTrace.debug("responseSummary: " + str(responseSummary))

    summary = responseSummary['choices'][0]['message']['content'].strip()
    
    logger.debug("Summary: " + summary)

    return summary

# ----------------------
# get keywords for the image generator and return the keywords
#
def getAbstractForImageGen(inputText):

    # extract the keywords from the summary

    logger.info("Extracting...")
    logger.debug("Prompt for abstraction: " + promptForAbstraction)    

    prompt = promptForAbstraction + "'''" + inputText + "'''"
    loggerTrace.debug ("prompt for extract: " + prompt)

    responseForImage = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": prompt}
        ]              
    )

    loggerTrace.debug("responseForImageGen: " + str(responseForImage))

    # extract the abstract from the response
    abstract = responseForImage['choices'][0]['message']['content'].strip() 
    
    # Clean up the response from OpenAI
    # delete text before the first double quote
    abstract = abstract[abstract.find("\"")+1:]
    # delete text before the first colon
    abstract = abstract[abstract.find(":")+1:]
    # eliminate phrases that are not useful for image generation
    badPhrases = ["the concept of", "in the supplied text is", "the most interesting concept"
                    "in the text is"]
    for phrase in badPhrases:
        # compilation step to escape the word for all cases
        compiled = re.compile(re.escape(phrase), re.IGNORECASE)
        res = compiled.sub(" ", abstract)
        abstract = str(res) 

    logger.info("Abstract: " + abstract)

    return abstract

# ----------------------
# get images and return the urls
#
def getImageURL(phrase):

    # use the keywords to generate an image

    prompt = "Generate a picture" 
    # add a modifier to the phrase
    # pick random modifiers
    import random
    random.shuffle(imageModifiersArtist)
    random.shuffle(imageModifiersMedium)
    prompt = prompt + imageModifiersArtist[0] + imageModifiersMedium[0]

    prompt = f"{prompt} for the following concept: {phrase}"

    logger.info("Generating image...")
    logger.info("image prompt: " + prompt)

    # use openai to generate a picture based on the summary
    responseImage = openai.Image.create(
        prompt= prompt,
        n=4,
        size="512x512"
        )
    
    loggerTrace.debug("responseImage: " + str(responseImage))

    image_url = [responseImage['data'][0]['url']] * 4
    image_url[1] = responseImage['data'][1]['url']
    image_url[2] = responseImage['data'][2]['url']
    image_url[3] = responseImage['data'][3]['url']

    return image_url



# ----------------------
# main program starts here
#
#
#

class processStep(IntEnum):
    NoneSpecified = 0
    Audio = 1
    Transcribe = 2
    Summarize = 3
    Keywords = 4
    Image = 5

# set up logging
logging.basicConfig(level=logging.WARNING, format=' %(asctime)s - %(levelname)s - %(message)s')

# set the OpenAI API key
openai.api_key_path = 'creepy photo secret key'

# check for running over SSL
isOverSSL = False
if ssl.OPENSSL_VERSION:
    isOverSSL = True

# create a directory if one does not exist
if not os.path.exists("history"):
    os.makedirs("history")

parser = argparse.ArgumentParser()
parser.add_argument("-s", "--savefiles", help="save the files", action="store_true") # optional argument
parser.add_argument("-d", "--debug", help="0:info, 1:prompts, 2:responses", type=int) # optional argument
parser.add_argument("-w", "--wav", help="use audio from file", type=str, default=0) # optional argument
parser.add_argument("-t", "--transcript", help="use transcript from file", type=str, default=0) # optional argument
parser.add_argument("-T", "--summary", help="use summary from file", type=str, default=0) # optional argument
parser.add_argument("-k", "--keywords", help="use keywords from file", type=str, default=0) # optional argument
parser.add_argument("-i", "--image", help="use image from file", type=str, default=0) # optional argument

args = parser.parse_args()

# set the debug level
logger.setLevel(logging.INFO)

if args.debug == 1:
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug level set to show prompts")
elif args.debug == 2:
    logger.setLevel(logging.DEBUG)
    loggerTrace.setLevel(logging.DEBUG)
    logger.debug("Debug level set to show prompts and response JSON")


# if we're given a file then start at that step
# check in order so that processStartStep will be the maximum value

firstProcessStep = processStep.NoneSpecified
if args.wav != 0:
    firstProcessStep = processStep.Audio
elif args.image != 0: 
    firstProcessStep = processStep.Image
elif args.keywords != 0: 
    firstProcessStep = processStep.Keywords
elif args.summary != 0: 
    firstProcessStep = processStep.Summarize
elif args.transcript != 0: 
    firstProcessStep  = processStep.Transcribe




# ----------------------
# Main Loop 
#

done = False  # set to true to exit the loop
loopDelay = 60 # delay between loops in seconds

while not done:

    if firstProcessStep > processStep.Audio or args.wav != 0:

        # we have file parameters, so only loop once
        numLoops = 1
        loopDelay = 0   # no delay if we're not looping

    else:
        # no command line input parameters so prompt the user for a command

        # print menu
        print("\r\n\n\n")
        print("Commands:")
        print("   o: once, record and display; default")
        print("   a: auto mode, record, display, and loop")
        print("   q: quit")

        # wait for the user to press a key
        inputCommand = input("Type a command ...")

        if inputCommand == 'q': # quit
            done = True
            numLoops = 0
            loopDelay = 0

        elif inputCommand == 'a': # auto mode
            numLoops = loopsMax
            print("Will loop: " + str(numLoops) + " times")
            
        else: # default is once
            numLoops = 1
            loopDelay = 0
            firstProcessStep = processStep.Audio

    # loop will normally process audio and display the images
    # but if we're given a file then start at that step (processStep)
    for i in range(0,numLoops,1):

        # format a time string to use as a file name
        timestr = time.strftime("%Y%m%d-%H%M%S")

        soundFileName = ""
        transcript = ""
        summary = ""
        keywords = ""
        imageURL = ""

        # Audio
        if firstProcessStep <= processStep.Audio:

            qBlinkControl.put(constBlinkAudioCapture)

            if args.wav == 0:
                # record audio from the default microphone
                soundFileName = recordAudioFromMicrophone()

                if args.savefiles:
                    #copy the file to a new name with the time stamp
                    shutil.copy(soundFileName, "history/" + timestr + "-recording" + ".wav")
                    soundFileName = "history/" + timestr + "-recording" + ".wav"
        
            else:
                # use the file specified by the wav argument
                soundFileName = args.wav
                logger.info("Using audio file: " + args.wav)

            qBlinkControl.put(constBlinkStop)
    
        # Transcribe
        if firstProcessStep <= processStep.Transcribe:
        
            qBlinkControl.put(constBlink1)

            if args.transcript == 0:
                # transcribe the recording
                transcript = getTranscript(soundFileName)

                if args.savefiles:
                    f = open("history/" + timestr + "-rawtranscript" + ".txt", "w")
                    f.write(transcript)
                    f.close()
            else:
                # use the text file specified 
                transcriptFile = open(args.transcript, "r")
                # read the transcript file
                transcript = transcriptFile.read()
                logger.info("Using transcript file: " + args.transcript)

            qBlinkControl.put(constBlinkStop)

        # Summary
        if firstProcessStep <= processStep.Summarize:

            """ Skip summarization for now
            qBlinkControl.put(constBlink2)

            if args.summary == 0:
                # summarize the transcript
                summary = getSummary(transcript)

                if args.savefiles:
                    f = open("history/" + timestr + "-summary" + ".txt", "w")
                    f.write(summary)
                    f.close()

            else:
                # use the text file specified by the transcript argument
                summaryFile = open(summaryArg, "r")
                # read the summary file
                summary = summaryFile.read()
                logger.info("Using summary file: " + summaryArg)
            
            qBlinkControl.put(constBlinkStop)
            """


        # Keywords    
        if firstProcessStep <= processStep.Keywords:

            qBlinkControl.put(constBlink3)

            if args.keywords == 0:
                # extract the keywords from the summary
                keywords = getAbstractForImageGen(transcript) 

                if args.savefiles:
                    f = open("history/" + timestr + "-keywords" + ".txt", "w")
                    f.write(keywords)
                    f.close()

            else:
                # use the extract file specified by the extract argument
                summaryFile = open(args.keywords, "r")
                # read the summary file
                keywords = summaryFile.read()
                logger.info("Using abstract file: " + args.keywords)

            qBlinkControl.put(constBlinkStop)

        # Image
        if firstProcessStep <= processStep.Image:

            qBlinkControl.put(constBlink4)

            if args.image == 0:

                # use the keywords to generate images
                imageURL = getImageURL(keywords)    

                # save the images from a urls into imgObjects[]
                imgObjects = []
                for numURL in range(len(imageURL)):

                    fileName = "history/" + "image" + str(numURL) + ".png"
                    urllib.request.urlretrieve(imageURL[numURL], fileName)

                    img = Image.open(fileName)

                    imgObjects.append(img)

                # combine the images into one image
                #widths, heights = zip(*(i.size for i in imgObjects))
                total_width = 512*2
                max_height = 512*2 + 50
                new_im = Image.new('RGB', (total_width, max_height))
                locations = [(0,0), (512,0), (0,512), (512,512)]
                count = -1
                for loc in locations:
                    count += 1
                    new_im.paste(imgObjects[count], loc)

                # add text at the bottom
                draw = ImageDraw.Draw(new_im)
                draw.rectangle(((0, new_im.height - 50), (new_im.width, new_im.height)), fill="black")
                font = ImageFont.truetype("arial.ttf", 18)
                # decide if text will exceed the width of the image
                #textWidth, textHeight = font.getsize(text)
                draw.text((10, new_im.height - 30), keywords, (255,255,255), font=font)

                # save the combined image
                newFileName = "history/" + timestr + "-image" + ".png"
                new_im.save(newFileName)

                #if args.savefiles and args.image == 0:
                #os.rename("image.png", timestr + "-image" + ".png")
                #os.rename('combined.png', timestr + "-image" + ".png")

                imageURL = "file://" + os.getcwd() + "/" + newFileName
                logger.debug("imageURL: " + imageURL)
            
            else:
                imageURL = [args.image ]
                logger.info("Using image file: " + args.image )

            qBlinkControl.put(constBlinkStop)
            
        # Display

        if isOverSSL:
            # don't try to disply
            pass
        else:
            # display the image
            qBlinkControl.put(constBlinkSlow)
            logger.info("Displaying image...")
            webbrowser.open(imageURL)

            qBlinkControl.put(constBlinkStop)

        #delay
        print("delaying " + str(loopDelay) + " seconds...")
        time.sleep(loopDelay)
        # clear the queue in case we're not on an RPi
        qBlinkControl.queue.clear()
        qBlinkControl.put(constBlinkStop)


# all done
if not g_isMacOS:
    # Stop the LED thread
    qBlinkControl.put(constBlinkDie)
    led_thread1.join()

    # Clean up the GPIO pins
    GPIO.cleanup()

# exit the program
print("\r\n")
exit()





