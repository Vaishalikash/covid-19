import warnings

import numpy as np 
from scipy.optimize import curve_fit 

from .utils import normalize, restore


__all__ = ['GrowthCOVIDModel', '_exp_func', '_logistic_func']


def _exp_func(x, a, b, c):
    """Exponential function of a single variable, x.
    
    Parameters
    ----------
    x : float or numpy.ndarray
        Input data.
    a : float
        First parameter.
    b : float
        Second parameter.
    c : float
        Third parameter.
    
    Returns
    -------
    float or numpy.ndarray
        a * exp(b * x) + c
    """
    return a * np.exp(b * x) + c


def _logistic_func(x, a, b, c, d):
    """Logistic function of a single variable, x.
    
    Parameters
    ----------
    x : float or numpy.ndarray
        Input data.
    a : float
        First parameter.
    b : float
        Second parameter.
    c : float
        Third parameter.
    d : float
        Forth parameter.
    
    Returns
    -------
    float or numpy.ndarray
        a/(1 + exp(-c *(x-d)))+b
    """
    return a / (1 + np.exp(-c * (x - d))) + b


_growth_model_dispatcher = {
    'exponential': _exp_func,
    'logistic': _logistic_func,
    }


_ci_dispatcher = {
    90: 1.645, 
    95: 1.960, 
    98: 2.326, 
    99: 2.576,
}


class GrowthCOVIDModel(object):
    """A class to fit an exponential model to given data."""
    def __init__(
        self, function, normalize=True, confidence_interval=False, **kwargs
        ):
        """Constructor.
        
        Parameters
        ----------
        function : str
            Growth curve.
        normalize : bool, optional
            Should the data be normalized to [0, 1] range.
        confidence_interval : bool, optional
            Generate CI using fitted params of a given function 
            +/- standard deviation.
        kwargs : dict, optional
            If `confidence_interval` flag is set to True and both
            kwargs are specified, the confidence intervals with be
            calculated using sensitivity as a valid accuracy measure.
            If confidence_interval flag is set to True but no kwargs
            (or just a single keyword argument) are given the
            confidence interval will be calulated assuming there are
            no intrinsic errors on measured data.
            sensitivity : float
                Measure of the proportion of positives that are
                correctly identified (e.g., the percentage of sick
                people who are correctly identified as being infected).
            specificity : float
                Measure of the proportion of negatives that are 
                correctly identified (e.g., the percentage of healthy
                people who are correctly identified as not infected).
            ci_level : int
                Confidence interval level. Supported values are 90, 95,
                98 and 99 using the standard normal distribution as the
                critical value.
            daily_tests : numpy.ndarray
                Tests performed daily. Size of an array should match
                the size of confirmed cases while fitting growth model.
        """
        try:
            self.function = _growth_model_dispatcher[function]
        except:
            raise ValueError('Try `exponential` or `logistic` growth models.')
        self.normalize = normalize
        self.ci = confidence_interval
        if kwargs and len(kwargs)==4: 
            for kw in kwargs.keys():
                if kw == 'sensitivity':
                    assert isinstance(kwargs[kw], (float, )), \
                        'Sensitivity has to be a floating point number.'
                    self.sensitivity = kwargs[kw]
                elif kw == 'specificity':
                    assert isinstance(kwargs[kw], (float, )), \
                        'Specificity has to be a floating point number.'
                    self.specificity = kwargs[kw]
                elif kw == 'ci_level':
                    assert kwargs[kw] in [90, 95, 98, 99], \
                        'Supported confidence interval levels are 90, 95, 98 \
                        and 99.'
                    self.ci_level = kwargs[kw]
                elif kw == 'daily_tests':
                    self.daily_tests = kwargs[kw]
                else:
                    self.sensitivity = None
                    self.specificity = None
                    self.ci_level = None
                    self.daily_tests = None
        elif kwargs and len(kwargs)!=4:
            warnings.warn(
                'One or more keyword arguments is invalid.'
                'Confidence interval will be calulated assuming there are no '
                'intrinsic errors on measured data.')
            self.sensitivity = None
            self.specificity = None
            self.ci_level = None
            self.daily_tests = None
        else:
            self.sensitivity = None
            self.specificity = None
            self.ci_level = None
            self.daily_tests = None
                    
    def fit(self, confirmed_cases):
        """Fit the data to the growth function.
        
        Parameters
        ----------
        confirmed_cases : numpy.ndarray
            Cumulative number of confirmed infected COVID-19 cases per 
            day.
        
        Returns
        -------
        x : numpy.ndarray
            The independent variable where the data is measured.
        fitted : numpy.ndarray
            Fitted growth function with lower and upper bound if
            `confidence_interval` is set to True.
        """
        self.confirmed_cases = confirmed_cases

        if self.normalize:
            y = normalize(confirmed_cases)
        else: 
            y = confirmed_cases
        x = np.arange(confirmed_cases.size)
        self.popt, self.pcov = curve_fit(self.function, x, y)
        fitted = self.function(x, *self.popt)

        if self.ci and not self.sensitivity:
            self.perr = np.sqrt(np.diag(self.pcov))
            lower_bound = self.function(x, *(self.popt - self.perr))
            upper_bound = self.function(x, *(self.popt + self.perr))
            if self.normalize: 
                fitted = restore(fitted, self.confirmed_cases)
                lower_bound = restore(lower_bound, self.confirmed_cases)
                upper_bound = restore(upper_bound, self.confirmed_cases)
            fitted = np.r_[
                lower_bound.reshape(1, -1), 
                fitted.reshape(1, -1), 
                upper_bound.reshape(1, -1)]

        elif (self.ci and self.sensitivity and self.specificity and 
                self.ci_level and self.daily_tests is not None):
            if self.normalize:
                fitted = restore(fitted, self.confirmed_cases)
            lower_bound, upper_bound = self.calculate_ci(
                self.sensitivity, 
                self.specificity, 
                fitted, 
                self.daily_tests, 
                self.ci_level)
            fitted = np.r_[
                lower_bound.reshape(1, -1), 
                fitted.reshape(1, -1), 
                upper_bound.reshape(1, -1)]
            # In order to figure out extrapolated bounds, functional
            # parameters of bounds have to be determined.
            # Following variables will be used if `predicted` method is
            # called.
            self.lb_reference = lower_bound
            self.ub_reference = upper_bound
            if self.normalize: 
                lower_bound = normalize(lower_bound)
                upper_bound = normalize(upper_bound)
            self.lb_popt, _ = curve_fit(self.function, x, lower_bound)
            self.ub_popt, _ = curve_fit(self.function, x, upper_bound)

        elif not self.ci and self.normalize:
            fitted = restore(fitted, self.confirmed_cases)
        return x, fitted

    def predict(self, n_days):
        """Predict the future n_days using the fitted growth function.
        
        Parameters
        ----------
        n_days : int
            Number of days to extrapolate.
        
        Returns
        -------
        x_future : numpy.ndarray
            The independent variable where the data is predicted.
        predicted : numpy.ndarray
            Extrapolated data with lower and upper bound if 
            `confidence_interval` is set to True.
        """
        assert isinstance(n_days, (int,)), 'Number of days must be integer.'
        size = self.confirmed_cases.size
        x_future = np.arange(size-1, size+n_days)
        predicted = self.function(x_future, *self.popt)

        if self.ci and not self.sensitivity:
            lower_bound = self.function(x_future, *(self.popt - self.perr))
            upper_bound = self.function(x_future, *(self.popt + self.perr))
            if self.normalize: 
                predicted = restore(predicted, self.confirmed_cases)
                lower_bound = restore(lower_bound, self.confirmed_cases)
                upper_bound = restore(upper_bound, self.confirmed_cases)
            predicted = np.r_[
                lower_bound.reshape(1, -1), 
                predicted.reshape(1, -1), 
                upper_bound.reshape(1, -1)]

        elif (self.ci and self.sensitivity and self.specificity and 
                self.ci_level and self.daily_tests is not None):
            lower_bound = self.function(x_future, *self.lb_popt)
            upper_bound = self.function(x_future, *self.ub_popt)
            if self.normalize:
                predicted = restore(predicted, self.confirmed_cases)
                lower_bound = restore(lower_bound, self.lb_reference)
                upper_bound = restore(upper_bound, self.ub_reference)
            predicted = np.r_[
                lower_bound.reshape(1, -1),
                predicted.reshape(1, -1),
                upper_bound.reshape(1, -1)]

        elif not self.ci and self.normalize:
            predicted = restore(predicted, self.confirmed_cases)

        return x_future, predicted

    @staticmethod
    def calculate_ci(
        sensitivity, 
        specificity, 
        fitted_curve,
        daily_tests,
        ci_level,
        ):
        """Return the lower and the upper bound for the total number of
        confirmed cases in time for selected confidence interval level.
        
        Parameters
        ----------
        sensitivity : float or numpy.ndarray
            Test sensitivity. If the sensitivity is different in
            different intervals, it should be stored in the array-like
            format where the length is the same as the length of the
            data.
        specificity : float or numpy.ndarray
            Test specificity. If the sensitivity is different in
            different intervals, it should be stored in the array-like
            format where the length is the same as the length of the
            data.
        fitted_curve : numpy.ndarray
            Fitted cumulative number of confirmed infected COVID-19 cases 
            per day.     
        daily_tests : numpy.ndarray
            Daily number of tests.
        ci_level : int
            Confidence interval level. Supported values are 90, 95,
            98 and 99 using the standard normal distribution as the
            critical value.
        Returns
        -------
        lower_bound_cumulative_cases : numpy.ndarray
            Array of shape (n, ) where n is the duration of modeled
            epidemics in days with values of lower CI bound. 
        upper_bound_cumulative_cases : numpy.ndarray
            Array of shape (n, ) where n is the duration of modeled
            epidemics in days with values of upper CI bound. 
        """
        positives = np.diff(fitted_curve)
        std_sensitivity_err = np.sqrt(np.divide(
            (1 - sensitivity) * sensitivity, 
            positives, 
            out=np.zeros(positives.shape, dtype=float), 
            where=positives!=0,
        ))
        sensitivity_ci = _ci_dispatcher[ci_level] * std_sensitivity_err
        lower_bound_sensitivity = np.abs(sensitivity - sensitivity_ci)
        lower_bound_true_positives = lower_bound_sensitivity * positives
        lower_bound_cumulative_cases = np.cumsum(lower_bound_true_positives) \
                                       + fitted_curve[0]
        
        # yesterday's test gives today's result 
        daily_tests = np.concatenate((
            np.array([daily_tests[0]]), daily_tests[:-1]))
        negatives = daily_tests[1:] - positives
        std_specificity_err = np.sqrt(np.divide(
            (1 - specificity) * specificity,
            negatives,
            out=np.zeros(negatives.shape, dtype=float), 
            where=negatives!=0,
        ))
        specificity_ci = _ci_dispatcher[ci_level] * std_specificity_err
        upper_bound_specificity = np.abs(specificity + specificity_ci)
        upper_bound_true_negatives = upper_bound_specificity * negatives
        upper_bound_false_negatives = negatives - upper_bound_true_negatives
        upper_bound_true_positives = upper_bound_false_negatives + positives
        upper_bound_cumulative_cases = np.cumsum(upper_bound_true_positives) \
                                       + fitted_curve[0]
        # bounds start from the same exact point because a single data
        # point is lost after fitted cases differentiation in th first
        # line of the method: positives = np.diff(fitted_curve)
        lower_bound_cumulative_cases = np.concatenate((
            np.array([fitted_curve[0]]), lower_bound_cumulative_cases))
        upper_bound_cumulative_cases = np.concatenate((
            np.array([fitted_curve[0]]), upper_bound_cumulative_cases))

        return lower_bound_cumulative_cases, upper_bound_cumulative_cases