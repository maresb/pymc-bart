# pylint: disable=unused-argument
# pylint: disable=arguments-differ
#   Copyright 2022 The PyMC Developers
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from multiprocessing import Manager
import aesara.tensor as at
import numpy as np

from aeppl.logprob import _logprob
from aesara.tensor.random.op import RandomVariable
from aesara.tensor.var import Variable

from pandas import DataFrame, Series

from pymc.distributions.distribution import Distribution, _moment

from .utils import _sample_posterior

__all__ = ["BART"]


class BARTRV(RandomVariable):
    """Base class for BART."""

    name = "BART"
    ndim_supp = 1
    ndims_params = [2, 1, 0, 0, 1]
    dtype = "floatX"
    _print_name = ("BART", "\\operatorname{BART}")
    all_trees = None

    def _supp_shape_from_params(self, dist_params, rep_param_idx=1, param_shapes=None):
        if isinstance(self.X, Variable):
            shape = self.X.shape[0].eval()
        else:
            shape = self.X.shape[0]
        return (shape,)

    @classmethod
    def rng_fn(cls, rng=None, X=None, Y=None, m=None, alpha=None, split_prior=None, size=None):
        if not cls.all_trees:
            if size is not None:
                return np.full((size[0], cls.Y.shape[0]), cls.Y.mean())
            else:
                return np.full(cls.Y.shape[0], cls.Y.mean())
        else:
            return _sample_posterior(cls.all_trees, cls.X, rng=rng).squeeze()


bart = BARTRV()


class BART(Distribution):
    """
    Bayesian Additive Regression Tree distribution.

    Distribution representing a sum over trees

    Parameters
    ----------
    X : array-like
        The covariate matrix.
    Y : array-like
        The response vector.
    m : int
        Number of trees
    alpha : float
        Control the prior probability over the depth of the trees. Even when it can takes values in
        the interval (0, 1), it is recommended to be in the interval (0, 0.5].
    split_prior : array-like
        Each element of split_prior should be in the [0, 1] interval and the elements should sum to
        1. Otherwise they will be normalized.
        Defaults to 0, i.e. all covariates have the same prior probability to be selected.
    """

    def __new__(
        cls,
        name,
        X,
        Y,
        m=50,
        alpha=0.25,
        split_prior=None,
        **kwargs,
    ):
        manager = Manager()
        cls.all_trees = manager.list()

        X, Y = preprocess_xy(X, Y)

        if split_prior is None:
            split_prior = []

        bart_op = type(
            f"BART_{name}",
            (BARTRV,),
            dict(
                name="BART",
                all_trees=cls.all_trees,
                inplace=False,
                initval=Y.mean(),
                X=X,
                Y=Y,
                m=m,
                alpha=alpha,
                split_prior=split_prior,
            ),
        )()

        Distribution.register(BARTRV)

        @_moment.register(BARTRV)
        def get_moment(rv, size, *rv_inputs):
            return cls.get_moment(rv, size, *rv_inputs)

        cls.rv_op = bart_op
        params = [X, Y, m, alpha, split_prior]
        return super().__new__(cls, name, *params, **kwargs)

    @classmethod
    def dist(cls, *params, **kwargs):
        return super().dist(params, **kwargs)

    def logp(self, x, *inputs):
        """Calculate log probability.

        Parameters
        ----------
        x: numeric, TensorVariable
            Value for which log-probability is calculated.

        Returns
        -------
        TensorVariable
        """
        return at.zeros_like(x)

    @classmethod
    def get_moment(cls, rv, size, *rv_inputs):
        mean = at.fill(size, rv.Y.mean())
        return mean


def preprocess_xy(X, Y):
    if isinstance(Y, (Series, DataFrame)):
        Y = Y.to_numpy()
    if isinstance(X, (Series, DataFrame)):
        X = X.to_numpy()

    Y = Y.astype(float)
    X = X.astype(float)

    return X, Y


@_logprob.register(BARTRV)
def logp(op, value_var, *dist_params, **kwargs):
    _dist_params = dist_params[3:]
    value_var = value_var[0]
    return BART.logp(value_var, *_dist_params)  # pylint: disable=no-value-for-parameter
