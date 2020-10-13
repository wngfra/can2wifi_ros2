# Copyright (c) 2020 wngfra
# Use of this source code is governed by the Apache-2.0 license, see LICENSE

from collections import deque
import socket
import sys

import numpy as np
import rclpy
from rclpy.node import Node

from tactile_interfaces.msg import TactileSignal
from tactile_interfaces.srv import ChangeState


THRESHOLD_MU = 1
THRESHOLD_SIGMA = 1


STATE_LIST = {
    0:  'calibration',
    1:  'recording',
    99: 'termination'
}
"""
_STATE_LIST lists available node states.
Node States
----------------------------------------
0: Calibration state (publish no data)
1: Recording state (publish data)
"""


class TactileSignalPublisher(Node):
    """
    A node class for tactile signal publisher.
    The node receives tactile signals in bytes via UDP and converts the data to array and publish to ROS2 network.
    Runtime node state switch is implemented.
    """

    def __init__(self):
        super().__init__('tactile_publisher')

        # Parameters are set via ROS2 parameter server.

        self.declare_parameters(
            namespace='',
            parameters=[
                ('ip', "0.0.0.0"),
                ('port', 10240),
                ('calibration_size', 30)
            ]
        )
        ip = self.get_parameter('ip').get_parameter_value().string_value
        port = self.get_parameter('port').get_parameter_value().integer_value
        calibration_size = self.get_parameter(
            'calibration_size').get_parameter_value().integer_value

        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.bind((ip, port))

        self.__state = 0

        # Queue of data for calibration
        self.__calibration_queue = deque(maxlen=calibration_size)
        self.__reference_value = np.zeros(16)

        self.__publisher = self.create_publisher(
            TactileSignal, '/tactile_signals', 10)
        self.__srv = self.create_service(
            ChangeState, '/tactile_publisher/change_state', self.change___statecallback)

        # Publisher rate 0.03s
        self.__timer = self.create_timer(0.03, self.timer_callback)

        self.get_logger().info('Node started in state: calibration')

    def timer_callback(self):
        data, addr = self.__sock.recvfrom(1024)
        values = [int.from_bytes(data[i:i+2], 'big', signed=False)
                  for i in range(0, len(data), 2)]

        if self.__state == 1:  # Recording state
            if len(self.__calibration_queue) == self.__calibration_queue.maxlen:
                self.__reference_value = np.average(
                    self.__calibration_queue, axis=0)

                msg = TactileSignal()
                msg.header.frame_id = 'world'
                msg.header.stamp = self.get_clock().now().to_msg()
                try:
                    data = np.array(values, dtype=np.int32) - \
                        self.__reference_value.astype(np.int32)
                    data[data <= 3] = 0.0
                    if np.mean(data) <= THRESHOLD_MU and np.var(data) >= THRESHOLD_SIGMA**2:
                        data.fill(0)

                    msg.addr = addr[0] + ":" + str(addr[1])
                    msg.data = data
                    self.__publisher.publish(msg)
                except Exception as error:
                    self.get_logger().error(str(error))
            else:
                self.get_logger().error("Uncalibrated sensor!")
                raise Exception("Calibration queue is not filled.")
        elif self.__state == 0:  # Calibration state
            if len(values) == 16:
                self.__calibration_queue.append(values)
        elif self.__state == 99:
            self.get_logger().warn("Tactile publisher terminated.")
            self.destroy_node()

    def change___statecallback(self, request, response):
        if request.transition != self.__state:
            try:
                if request.transition in STATE_LIST.keys():
                    self.__state = request.transition

                    response.success = True
                    response.info = "OK"

                    self.get_logger().info(
                        "Changed to state: {}".format(STATE_LIST[self.__state]))
                else:
                    raise Exception("Undefined state")
            except Exception as error:
                response.success = False
                response.info = str(error)

                self.get_logger().error("Wrong transition! Reverting to state: calibration")
                self.__state = 0
        else:
            response.success = True
            response.info = "No transition needed!"

            self.get_logger().info(
                "In state: {}".format(STATE_LIST[self.__state]))

        return response


def main(args=None):
    rclpy.init(args=args)
    pub = TactileSignalPublisher()
    rclpy.spin(pub)
    rclpy.shutdown()


if __name__ == '__main__':
    main()