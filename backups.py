import random
import time


def sleep_randomly(min_time=1, max_time=2):
    """
    Sleep for a random duration between min_time and max_time. Used for randomisation if needed

    :param min_time: Minimum sleep time.
    :param max_time: Maximum sleep time.
    """
    time.sleep(random.uniform(min_time, max_time))
