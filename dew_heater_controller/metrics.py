"""Math helpers for dew point calculations."""

import math


def dew_point_c(temp_c: float, humidity: float) -> float:
    """Magnus approximation for dew point in Celsius."""
    a = 17.27
    b = 237.7
    gamma = (a * temp_c / (b + temp_c)) + math.log(humidity / 100.0)
    return (b * gamma) / (a - gamma)
