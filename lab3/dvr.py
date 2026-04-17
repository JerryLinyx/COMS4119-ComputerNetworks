""""
Columbia University - CSEE 4119 Computer Network
Assignment 3 - Distance Vector Routing

dvr.py - the Distance Vector Routing (DVR) program announces its distance vector to its neighbors and 
updates its routing table based on the received routing tables from its neighbors
"""
import sys
import socket
import time

class NetworkInterface():
    """
    DO NOT EDIT.
    
    Provided interface to the network. In addition to typical send/recv methods,
    it also provides a method to receive an initial message from the network, which
    contains the costs to neighbors. 
    """
    def __init__(self, network_port, network_ip):
        """
        Constructor for the NetworkInterface class.

        Parameters:
            network_port : int
                The port the network is listening on.
            network_ip : str
                The IP address of the network.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((network_ip, network_port))
        self.init_msg = self.sock.recv(4096).decode() # receive the initial message from the network
        
    def initial_costs(self): 
        """
        Return the initial message received from the network in following format:
        <node_id>. <neighbor_1>:<cost_1>,...,<neighbor_n>:<cost_n>

        node_id is the unique identifier for this node, i.e., dvr.py instance. 
        Neighbor_i is the unique identifier for direct neighbor nodes. All identifiers
        and costs are specified in the topology file.
        """
        return self.init_msg
    
    def send(self, message):
        """
        Send a message to all direct neigbors.

        Parameters:
            message : bytes
                The message to send.
        
        Returns:
            None
        """
        message_len = len(message)
        packet = message_len.to_bytes(4, byteorder='big') + message
        self.sock.sendall(packet)
    
    def recv(self, length):
        """
        Receive a message from neighbors. Behaves exactly like socket.recv()

        Parameters:
            length : int
                The length of the message to receive.
        
        Returns:
            bytes
                The received message.
        """
        return self.sock.recv(length)
    
    def close(self):
        """
        Close the socket connection with the network.
        """
        self.sock.close()
    

if __name__ == '__main__':
    network_ip = sys.argv[1] # the IP address of the network
    network_port = int(sys.argv[2]) # the port the network is listening on
 
    net_interface = NetworkInterface(network_port, network_ip) # initialize the network interface

    # get the initial costs to your neighbors to help initialize your vector and table. Format is:
    # <node_id>. <neighbor_1>:<cost_1>,...,<neighbor_n>:<cost_n>
    init_costs = net_interface.initial_costs() 
    print(init_costs)

    """Below is an example of how to use the network interface and log. Replace it with your distance vector routing protocol"""

    # Create a log file
    log_file = open("log.txt", "w")

    # Example of sending a message to the network, 
    # which is guaranteed to be broadcast to your neighbors
    net_interface.send(b"Hello neighbor")
        
    # Example of receiving a message from the network,
    # which is guaranteed to be from a neighbor
    msg = net_interface.recv(1024) # receive the message from the network. Note: May return content from multiple nodes. 

    # Write the message to the log file. Use flush to ensure the message is written to the file immediately
    log_file.write(msg.decode())
    log_file.flush() # IMPORTANT
 
    # Wait for 5 seconds before closing the interface
    time.sleep(5)

    # Close the interface with the network
    net_interface.close()

    # Close the log file
    log_file.close()