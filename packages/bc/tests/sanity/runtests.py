import unittest

import os
import subprocess


def call_command(command_to_call):
    result = subprocess.check_output(command_to_call, shell=True)
    return result[:-1].decode("utf-8") 


class TestBC(unittest.TestCase):

    def test_divide(self):
        result = call_command("echo '6.5 / 2.7' | bc")
        self.assertEqual( result, '2')

    def test_sum(self):
        result = call_command("echo '2 + 5' | bc")
        self.assertEqual( result, '7')

    def test_difference(self):
        result = call_command("echo '10 - 4' | bc")
        self.assertEqual( result, '6')

    def test_multiplying(self):
        result = call_command("echo '3 * 8' | bc")
        self.assertEqual( result, '24')

    def test_scale(self):
        result = call_command("echo 'scale = 2; 2 / 3' | bc")
        self.assertEqual( result, '.66')

    def test_remainder(self):
        result = call_command("echo '6 % 4' | bc")
        self.assertEqual( result, '2')

    def test_exponent(self):
        result = call_command("echo '10^2' | bc")
        self.assertEqual( result, '100')


if __name__ == '__main__':
    unittest.main()

