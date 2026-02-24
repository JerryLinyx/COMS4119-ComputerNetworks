# 
# Columbia University - CSEE 4119 Computer Networks
# Assignment 1 - Adaptive video streaming
#
# video_player.py 
# 
# put path of the video chunk to the queue and the 
# video player will automatically play them
#
# require opencv, install with pip install opencv-python
#

import cv2

def rescale_frame(frame, scale_factor):
    """
    Downsample frame so that its resolution is <scale_factor>*<scale_factor> higher or lower
    than that of <frame>
    """
    width = int(frame.shape[1] * scale_factor)
    height = int(frame.shape[0] * scale_factor)
    dim = (width, height)
    return cv2.resize(frame, dim, interpolation =cv2.INTER_AREA)


def play_chunks(chunks_queue):
    """
    display a frame whenever one arrives in the queue
    """
    quit = False
    while not quit:
        chunk_path = chunks_queue.get()
        cap = cv2.VideoCapture(chunk_path)
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = rescale_frame(frame, 1080/frame.shape[0])
            cv2.imshow('Video Player: Press q to quit',frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                quit = True
                break