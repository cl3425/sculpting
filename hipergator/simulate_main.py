"""
This is the home of the main function for the transit simulation machinery. It uses general helper functions from simulate_helpers and a transit workhorse code
from simulate_transit to output transit statuses for simulated systems. Likelihood_main.py will read in those files and compute logL. 
"""

import json
import sys
import numpy as np
from numpy import log, exp, pi
import pandas as pd
import scipy
import scipy.stats as stats
import random
from scipy.stats import gaussian_kde, loguniform
from math import lgamma
from glob import glob
import os
import seaborn as sns
import matplotlib as mpl
import matplotlib.pyplot as plt
from simulate_transit import * 
from simulate_helpers import *
#from simulate_transit import model_van_eylen

### variables for HPG
task_id = os.getenv('SLURM_ARRAY_TASK_ID')
path = '/blue/sarahballard/c.lam/sculpting/'

### variables for local
#path = '/Users/chrislam/Desktop/sculpting/' # new computer has different username
berger_kepler = pd.read_csv(path+'berger_kepler_stellar17.csv') # crossmatched with Gaia via Bedell
pnum = pd.read_csv(path+'pnum_plus_cands.csv')
pnum = pnum.drop_duplicates(['kepid'])
k = pnum.koi_count.value_counts() 
k = pd.Series([len(berger_kepler)-np.sum(k), 244, 51, 12, 8, 1]) 
G = 6.6743e-8 # gravitational constant in cgs

def prior_grid_logslope(cube, ndim, nparams, gi_m, gi_b, gi_c):
	"""
	Each model run will use an evenly spaced (m,b, cutoff) tuple on a discrete 11x11x11 3D grid
	We're doing log(time), so slope is sampled linearly (everything gets logged together later)
	If a cutoff results in a zero probability, don't bother 

	gi_m: grid index on m axis
	gi_b: grid index on b axis
	gi_c: grid index for cutoff time axis
	"""
	#cube[0] = -1e-9*np.logspace(8,10,11)[gi_m] # convert from year to Gyr
	cube[0] = np.linspace(-2,0,11)[gi_m] 
	cube[1] = np.linspace(0,1,11)[gi_b]
	#cube[2] = np.logspace(1e8,1e10,11)
	cube[2] = np.logspace(8,10,11)[gi_c] # in Ballard et al in prep, they use log(yrs) instead of drawing yrs from logspace
	return cube

def better_loglike(lam, k):
	"""
	Calculate Poisson log likelihood
	Changed 0 handling from simulate.py to reflect https://www.aanda.org/articles/aa/pdf/2009/16/aa8472-07.pdf

	Params: 
	- lam: model predictions for transit multiplicity (list of ints)
	- k: Kepler transit multiplicity (list of ints); can accept alternate ground truths as well

	Returns: Poisson log likelihood (float)
	"""

	logL = []
	#print(lam)
	for i in range(len(lam)):
		if lam[i]==0:    
			term3 = -lgamma(k[i]+1)
			term2 = -lam[i]
			term1 = 0
			logL.append(term1+term2+term3)
		else:
			term3 = -lgamma(k[i]+1)
			term2 = -lam[i]
			term1 = k[i]*np.log(lam[i])
			logL.append(term1+term2+term3)

	return np.sum(logL)

def loglike_direct_draw_better(cube, ndim, nparams, k):
	"""
	Run model per hyperparam draw and calculate Poisson log likelihood
	2nd iteration of bridge function between model_direct_draw() and better_logllike()
	Includes geometric transit multiplicity and 0 handling.
	Commented out the zero handling because it's wrong.

	Params: 
	- cube: hyperparam cube of slope and intercept
	- ndim: number of dimensions
	- nparams: number of parameters
	- k: from Berger et al 2020
	Returns: Poisson log-likelihood
	"""

	# retrieve prior cube and feed prior-normalized hypercube into model to generate transit multiplicities
	lam, geom_lam, transits, intact_fractions, amds, eccentricities, inclinations_degrees = model_direct_draw(cube)
	#lam = [1e-12 if x==0.0 else x for x in lam] # avoid -infs in logL by turning 0 lams to 1e-12
	#geom_lam = [1e-12 if x==0.0 else x for x in geom_lam] # ditto
	logL = better_loglike(lam, k)
	geom_logL = better_loglike(geom_lam, k)
	
	return logL, lam, geom_lam, geom_logL, transits, intact_fractions, amds, eccentricities, inclinations_degrees


"""
For each of the three main hyperparams, I make 50 simulations (50000 total simulations). I use the original way of sampling eccentricities.
I output each simulation to a folder and never run them again. The I/O for calculating logLs will be worth not having to re-run simulations.
For each of the 50K resulting lambdas, I create 10 of varying fraction of systems with planets (the fourth hyperparam).
I run separate code to compute logLs for each 4-hyperparam combination and plot that as I have done before.
I do the same, now using the Rayleigh-Limbach hybrid eccentricity distribution. 

Eventually, I do the same using pymultinest. A man can dream.

WHERE I LEFT OFF: 
- Add logic in simulate_transit for skipping simulations if cutoff occurs more than once after probability has reached zero (use the first one for all)
- Also don't vary cutoffs for m=0 case.
"""

def unit_test(k):
	### use fiducial values of m, b, cutoff, and frac for now to test eccentricity models
	m = -0.3
	b = 0.5
	cutoff = 1e10 # yrs
	frac = 0.4 # fraction of FGK dwarfs with planets
	cube = [m, b, cutoff, frac]

	berger_kepler_planets = model_van_eylen(berger_kepler.iso_age, berger_kepler, 'limbach', cube)
	transiters_berger_kepler = berger_kepler_planets.loc[berger_kepler_planets['transit_status']==1]
	transit_multiplicity = transiters_berger_kepler.groupby('kepid').count()['transit_status'].reset_index().groupby('transit_status').count().reset_index().kepid

	# make sure the 6-multiplicity bin is filled in with zero and ignore zero-bin
	k[6] = 0
	k = k[1:].reset_index()[0]
	print(list(transit_multiplicity))
	print(list(k))

	# calculate log likelihood
	logL = better_loglike(list(transit_multiplicity), list(k))
	print(logL)
	print(better_loglike([466.8, 72.8, 14.8, 13.2, 7.6, 2.4], k))

	return

# how many params, how many dims, initialize cube
ndim = 3
nparams = 3
cube = [0, 0, 0]

def main(cube, ndim, nparams, k):
	"""
	For each of the three main hyperparams, I make 50 simulations (50000 total simulations). I use the original way of sampling eccentricities.
	I output each simulation to a folder and never run them again. The I/O for calculating logLs will be worth not having to re-run simulations.
	For each of the 50K resulting lambdas, I create 10 of varying fraction of systems with planets (the fourth hyperparam).
	I run separate code to compute logLs for each 4-hyperparam combination and plot that as I have done before.
	I do the same, now using the Rayleigh-Limbach hybrid eccentricity distribution. 

	Eventually, I do the same using pymultinest. A man can dream.

	Params: 
	- cube: [m, b, cutoff]
	- ndim: number of dimensions, will be 4 instead of 3 for pymultinest
	- nparams: number of parameters, will be 4 instead of 3 for pymultinest
	- k: ground truth transit multiplicity (Pandas Series)
	"""

	for gi_m in range(11):
		for gi_b in range(11):
			for gi_c in range(11):
				cube = prior_grid_logslope(cube, ndim, nparams, gi_m, gi_b, gi_c)
				for i in range(50):
					berger_kepler_planets = model_van_eylen(berger_kepler.iso_age, berger_kepler, 'limbach', cube)
					berger_kepler_planets.to_csv('/blue/sarahballard/c.lam/sculpting2/simulations/transits'+str(gi_m)+'_'+str(gi_b)+'_'+str(gi_c)+'_'+str(i)+'.csv')
	return

#unit_test(k)
main(cube, ndim, nparams, k)

