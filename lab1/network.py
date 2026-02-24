# 
# Columbia University - CSEE 4119 Computer Networks
# Assignment 1 - Adaptive video streaming
#
# network.py - network simulator that serves as a server to the 
#   actual client and a client to the actual server. It varies
#   link bandwidth based on an external file (e.g., bw.txt).

#!/usr/bin/env python3.10
import argparse
from socket import *
import threading
import time

bandwidths = {}

def createSocketToClient(p):
    """
    creating network listening socket

    arguments:
    p -- the listening port of the network
    """
    s = socket(AF_INET,SOCK_STREAM)
    s.bind(('',p))
    s.listen(1)
    return s

def connectSocketToClient(ts):
    """
    connecting network to client socket

    arguments:
    ts -- the listening socket
    """
    s, addr = ts.accept()
    return s

def connectSocketToServer(a, p):
    """
    connecting network to server socket

    arguments:
    a -- the server address
    p -- the listening port of the server
    """
    s = socket(AF_INET,SOCK_STREAM)
    s.bind(('',0))
    s.connect((a,p))
    return s

def setUpBandWidths(bwFileName):
    """
    reads in bandwidth file

    arguments:
    bwFileName -- name of the bandwidth file
    """
    for line in open(bwFileName, 'r').readlines():
        bandwidths[line.split(':')[0]] = line.split(':')[1].split('\n')[0]
    return True

def getCurrentBandWidth(st):
    """
    determines current bandwidth of the link

    arguments:
    st -- the start time of the client connection
    """
    n = time.time() - st
    lastBW = 10000000000
    for t in bandwidths.keys():
        if n > int(t):
            lastBW = bandwidths[t]
    return lastBW

def handleClientRequest(stc, sts): 
    """
    handling the clients request

    arguments:
    stc -- the socket connected to the client
    sts -- the socket connected to the server
    """
    buff_size = 2048
    while True:
        req = stc.recv(buff_size)
        if not req:
            break
        sts.sendall(req)

def handleServerResponse(sts, stc, st, l): 
    """
    handling the server's response (data)

    arguments:
    sts -- the socket connected to the server
    stc -- the socket connected to the client
    st -- the start time of the client connection
    l -- the latency of the network link
    """
    buff_size = 2000000000
    while True:
        c = sts.recv(buff_size)
        bw = getCurrentBandWidth(st)
        sdt = (len(c) * 8) / float(bw)
        d = max(sdt, float(l))
        time.sleep(d)
        stc.send(c)
  
if __name__ == '__main__':
    # accepts commandline arguments
    parser = argparse.ArgumentParser(
                    prog='network.py',
                    description='network.py simulates the network. It forwards data between the server/client programs and varies link conditions to test your implementation of the rate adaptation algorithm in the client.')
    parser.add_argument('networkPort', type=int, choices=range(49151,65535), metavar='networkPort: (49151 – 65535)')
    parser.add_argument('serverAddr', type=str)
    parser.add_argument('serverPort', type=int, choices=range(49151,65535), metavar='serverPort: (49151 – 65535)')
    parser.add_argument('bwFileName', type=str)
    parser.add_argument('latency', type=float)

    args = parser.parse_args()

    # reads in bandwidth file and connects required sockets
    setup = setUpBandWidths(args.bwFileName)

    socketToClient = createSocketToClient(args.networkPort)
    socketToClient = connectSocketToClient(socketToClient)
    socketToServer = connectSocketToServer(args.serverAddr, args.serverPort)

    startTime = time.time()
    # starts child thread that handles client requests
    t = threading.Thread(target=handleClientRequest, args=(socketToClient, socketToServer))
    t.start()
    
    # leaves parent thread to handle server responses
    handleServerResponse(socketToServer, socketToClient, startTime, args.latency)
