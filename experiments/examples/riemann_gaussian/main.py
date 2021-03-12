import os
import sys

import numpy as np

import bayesiancoresets as bc

# make it so we can import models/etc from parent folder
sys.path.insert(1, os.path.join(sys.path[0], '../common'))
import gaussian

M = 300
N = 600
d = 200
opt_itrs = 500  # for SparseVI
proj_dim = 100
pihat_noise = 0.75

mu0 = np.zeros(d)
Sig0 = np.eye(d)
Sig = np.eye(d)
SigL = np.linalg.cholesky(Sig)
th = np.ones(d)
Sig0inv = np.linalg.inv(Sig0)
Siginv = np.linalg.inv(Sig)
SigLInv = np.linalg.inv(SigL)

nm = sys.argv[1]
tr = sys.argv[2]

# generate data and compute true posterior
# use the trial # as the seed
np.random.seed(int(tr))

x = np.random.multivariate_normal(th, Sig, N)
mup, Sigp = gaussian.weighted_post(mu0, Sig0inv, Siginv, x, np.ones(x.shape[0]))
Sigpinv = np.linalg.inv(Sigp)

# for the algorithm, use the trial # and name as seed
np.random.seed(int(''.join([str(ord(ch)) for ch in nm + tr])) % 2 ** 32)

# compute constants for log likelihood function
xSiginv = x.dot(Siginv)
xSiginvx = (xSiginv * x).sum(axis=1)
logdetSig = np.linalg.slogdet(Sig)[1]

# create the log_likelihood function
log_likelihood = lambda samples: gaussian.gaussian_potentials(Siginv, xSiginvx, xSiginv, logdetSig, x, samples)

# create the sampler for the "optimally-tuned" Hilbert coreset
sampler_optimal = lambda n, w, ids: np.random.multivariate_normal(mup, Sigp, n)
tsf_optimal = bc.BayesianTangentSpaceFactory(log_likelihood, sampler_optimal, proj_dim)

# create the sampler for the "realistically-tuned" Hilbert coreset
U = np.random.rand()
muhat = U * mup + (1. - U) * mu0
Sighat = U * Sigp + (1. - U) * Sig0
# now corrupt the smoothed pihat
muhat += pihat_noise * np.sqrt((muhat ** 2).sum()) * np.random.randn(muhat.shape[0])
Sighat *= np.exp(-2 * pihat_noise * np.fabs(np.random.randn()))

sampler_realistic = lambda n, w, ids: np.random.multivariate_normal(muhat, Sighat, n)
tsf_realistic = bc.BayesianTangentSpaceFactory(log_likelihood, sampler_realistic, proj_dim)


############################
###Random projections in SparseVI for gradient computation
###the below is what you would do normally for a model where exact log-likelihood projection is unavailable
##create the sampler for the weighted posterior
# def sampler_w(n, wts, idcs):
#  w = np.zeros(x.shape[0])
#  w[idcs] = wts
#  muw, Sigw = gaussian.weighted_post(mu0, Sig0inv, Siginv, x, w)
#  return np.random.multivariate_normal(muw, Sigw, n)
# log_likelihood_w = log_likelihood
# tsf_w = bc.BayesianTangentSpaceFactory(log_likelihood, sampler_w, proj_dim)
############################

##############################
###Exact projection in SparseVI for gradient computation
# for this model we can do the tangent space projection exactly
def tsf_exact_w(wts, idcs):
    w = np.zeros(x.shape[0])
    w[idcs] = wts
    muw, Sigw = gaussian.weighted_post(mu0, Sig0inv, Siginv, x, w)
    nu = (x - muw).dot(SigLInv.T)
    Psi = np.dot(SigLInv, np.dot(Sigw, SigLInv.T))
    nu = np.hstack((nu.dot(np.linalg.cholesky(Psi)),
                    0.25 * np.sqrt(np.trace(np.dot(Psi.T, Psi))) * np.ones(nu.shape[0])[:, np.newaxis]))
    return nu


tsf_exact_optimal = lambda: tsf_exact_w(np.ones(x.shape[0]), np.arange(x.shape[0]))
rlst_idcs = np.arange(x.shape[0])
np.random.shuffle(rlst_idcs)
rlst_idcs = rlst_idcs[:int(0.1 * rlst_idcs.shape[0])]
rlst_w = np.zeros(x.shape[0])
rlst_w[rlst_idcs] = 2. * x.shape[0] / rlst_idcs.shape[0] * np.random.rand(rlst_idcs.shape[0])
tsf_exact_realistic = lambda: tsf_exact_w(2. * np.random.rand(x.shape[0]), np.arange(x.shape[0]))

##############################

# create coreset construction objects
sparsevi = bc.SparseVICoreset(tsf_exact_w, opt_itrs)
giga_optimal = bc.HilbertCoreset(tsf_optimal)
giga_optimal_exact = bc.HilbertCoreset(tsf_exact_optimal)
giga_realistic = bc.HilbertCoreset(tsf_realistic)
giga_realistic_exact = bc.HilbertCoreset(tsf_exact_realistic)
unif = bc.UniformSamplingCoreset(x.shape[0])
iht = bc.IHTCoreset(tsf_exact_optimal, proj_dim, 'IHT')
iht_2 = bc.IHTCoreset(tsf_exact_optimal, proj_dim, 'IHT-2')

algs = {'SVI': sparsevi,
        'GIGAO': giga_optimal,
        'GIGAOE': giga_optimal_exact,
        'GIGAR': giga_realistic,
        'GIGARE': giga_realistic_exact,
        'RAND': unif,
        'IHT': iht,
        'IHT-2': iht_2}
alg = algs[nm]

w = np.zeros((M + 1, x.shape[0]))
for m in range(2, M + 1, 1):
    print('trial: ' + tr + ' alg: ' + nm + ' ' + str(m) + '/' + str(M))
    alg.build(1, m)
    # store weights
    wts, idcs = alg.weights()
    w[m, idcs] = wts

muw = np.zeros((M + 1, mu0.shape[0]))
Sigw = np.zeros((M + 1, mu0.shape[0], mu0.shape[0]))
rklw = np.zeros(M + 1)
fklw = np.zeros(M + 1)
for m in range(2, M + 1):
    muw[m, :], Sigw[m, :, :] = gaussian.weighted_post(mu0, Sig0inv, Siginv, x, w[m, :])
    rklw[m] = gaussian.weighted_post_KL(mu0, Sig0inv, Siginv, x, w[m, :], reverse=True)
    fklw[m] = gaussian.weighted_post_KL(mu0, Sig0inv, Siginv, x, w[m, :], reverse=False)

if not os.path.exists('results/'):
    os.mkdir('results')
np.savez('results/results_' + nm + '_' + tr + '.npz', x=x, mu0=mu0, Sig0=Sig0, Sig=Sig, mup=mup, Sigp=Sigp, w=w,
         muw=muw, Sigw=Sigw, rklw=rklw, fklw=fklw)
