import fpga.geom as geom
import numpy as np
import pandas as pd


def robustRms(array):
    """Calculate a robust RMS of the array using the inter-quartile range

    Uses the standard conversion of IQR to RMS for a Gaussian.

    Parameters
    ----------
    array : `numpy.ndarray`
        Array for which to calculate RMS.

    Returns
    -------
    rms : `float`
        Robust RMS.
    """
    lq, uq = np.percentile(array, (25.0, 75.0))
    return 0.741 * (uq - lq)


def serialOverscanStats(image, readRows=(0, 4300)):
    """Calculate serial overscan levels and noise for all amplifiers.

    Parameters
    ----------
    image : `numpy.ndarray`
        Raw CCD Image

    Returns
    -------
    stats : `pd.DataFrame`
        DataFrame with stats for each amplifier.
    """
    exp = geom.Exposure()
    exp.image = image
    ampIms, osIms, _ = exp.splitImage()

    stats = [perAmpSerialOverScan(osIm[slice(*readRows)]) for osIm in osIms]
    return pd.DataFrame(stats, columns=['level', 'noise'])


def perAmpSerialOverScan(osIm, rowTrim=(0, 0), colTrim=(3, 3)):
    """Calculate median overscan level and rms noise for a given amplifier.

   Parameters
   ----------
   osIm : `numpy.ndarray`
       Serial Overscan data.

   Returns
   -------
   level : `float`
       Median level.
   rms : `float`
       Robust RMS.
   """
    rows = slice(rowTrim[0], osIm.shape[0] - rowTrim[1])
    cols = slice(colTrim[0], osIm.shape[1] - colTrim[1])

    trimmed = osIm[rows, cols]

    return np.median(trimmed), np.std(trimmed)


def ensureOverscansAreInRange(overscan, ampsConfig):
    """Check that overscan level/noise are in range.

   Parameters
   ----------
   overscan : `pd.DataFrame`
       Serial Overscan data.

   ampsConfig : `dict`
       Amplifiers configuration.

   Returns
   -------
   status : `str`
       Status of the overscans, OK or meaningful message otherwise.
   """
    warnings = []

    for level, rms, ampId, ampConfig in zip(overscan.level, overscan.noise, ampsConfig.keys(), ampsConfig.values()):
        minLevel, maxLevel = ampConfig['serialOverscanLevelLim']
        minRMS, maxRMS = ampConfig['serialOverscanNoiseLim']

        if (not minLevel < level < maxLevel) or (not minRMS < rms < maxRMS):
            warnings.append((ampId, int(level), round(rms, 1)))

        # this would be too long let's keep it short for STS sake
        #     warnings.append(f'amp{ampId} overscan level({level}) out of range({minLevel}:{maxLevel})')
        # if not minRMS<noise<maxRMS:
        #    warnings.append(f'amp{ampId} overscan noise({noise}) out of range({minRMS}:{maxRMS})')

    if not warnings:
        status = "OK"
    else:
        status = "overscan out of range ! " + \
                 " ".join([f'amp{ampId}(level={level} RMS={rms})' for ampId, level, rms in warnings])

    return status
