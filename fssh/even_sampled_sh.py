#!/usr/bin/env python
## @package fssh
#  Module responsible for propagating surface hopping trajectories

# fssh: program to run surface hopping simulations for model problems
# Copyright (C) 2018-2020, Shane Parker <shane.parker@case.edu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import print_function, division

import copy as cp

import numpy as np

from .fssh import TrajectoryCum

## Data structure to inform how new traces are spawned and weighted
class SpawnStack(object):
    def __init__(self, sample_stack, weight):
        self.sample_stack = sample_stack
        self.weight = weight

        self.izeta = None
        self.zeta = None

    def zeta(self):
        return self.zeta

    def next_zeta(self, random_state = np.random.RandomState()):
        if self.sample_stack is not None:
            if self.izeta is None:
                self.izeta = 0
            else:
                self.izeta += 1

            if self.izeta < len(self.sample_stack):
                self.zeta = self.sample_stack[self.izeta]["zeta"]
            else:
                raise Exception("Should I be returning None?")
                self.zeta = None
        else:
            self.zeta = random_state.uniform()

        return self.zeta

    def spawn(self):
        if self.sample_stack:
            samp = self.sample_stack[self.izeta]
            dw = samp["dw"]
            weight = self.weight * dw
            next_stack = samp["children"]
        else:
            weight = self.weight
            next_stack = None
        return self.__class__(next_stack, weight)

    @classmethod
    def build_simple(cls, nsamples, sample_depth, include_first=False):
        samples = np.sort(np.linspace(1.0, 0.0, nsamples, endpoint=include_first, retstep=False))
        dw = samples[1] - samples[0]

        forest = [ { "zeta" : s, "dw" : dw, "children" : None } for s in samples ]

        for d in range(1, sample_depth):
            leaves = cp.copy(forest)
            forest = [ { "zeta" : s, "dw" : dw, "children" : cp.deepcopy(leaves) } for s in samples ]

        return cls(forest, 1.0)


## Trajectory surface hopping using an even sampling approach
#
#  Related to the cumulative trajectory picture, but instead of hopping
#  stochastically, new trajectories are spawned at even intervals of the
#  of the cumulative probability distribution. This is an *experimental*
#  in principle deterministic algorithm for FSSH simulations.
class EvenSamplingTrajectory(TrajectoryCum):
    ## Constructor (see TrajectoryCum constructor)
    def __init__(self, *args, **options):
        TrajectoryCum.__init__(self, *args, **options)

        self.spawn_stack = cp.deepcopy(options["spawn_stack"])

        self.zeta = self.spawn_stack.next_zeta(self.random_state)

    def clone(self, spawn_stack=None):
        if spawn_stack is None:
            spawn_stack = self.spawn_stack

        out = EvenSamplingTrajectory(
                self.model,
                self.position,
                self.velocity * self.mass,
                self.rho,
                tracer=cp.deepcopy(self.tracer),
                queue = self.queue,
                last_velocity = self.last_velocity,
                state0 = self.state,
                t0 = self.time,
                previous_steps = self.nsteps,
                trace_every = self.trace_every,
                dt = self.dt,
                outcome_type = self.outcome_type,
                seed = None,
                electronics = self.electronics,
                spawn_stack = spawn_stack)
        return out

    ## given a set of probabilities, determines whether and where to hop
    # @param probs [nstates] numpy array of individual hopping probabilities
    #  returns [ (target_state, hop_weight) ]
    def hopper(self, probs):
        accumulated = self.prob_cum
        probs[self.state] = 0.0 # ensure self-hopping is nonsense
        gkdt = np.sum(probs)

        accumulated = 1 - (1 - accumulated) * np.exp(-gkdt)
        if accumulated > self.zeta: # then hop
            # where to hop
            hop_choice = probs / gkdt

            targets = [ { "target" : i,
                          "weight" : hop_choice[i],
                          "zeta" : self.zeta,
                          "prob" : accumulated,
                          "stack" : self.spawn_stack.spawn()} for i in range(self.model.nstates()) if i != self.state ]

            # reset probabilities and random
            self.zeta = self.spawn_stack.next_zeta()

            return targets

        self.prob_cum = accumulated
        return []

    ## hop_to_it for even sampling spawns new trajectories instead of enacting hop
    #
    #  hop_to_it must accomplish:
    #    - copy current trajectory
    #    - initiate hops on the copied trajectories
    #    - make no changes to current trajectory
    #    - set next threshold for spawning
    #
    # @param hop_to [nspawn] list of states and associated weights on which
    # @param electronics model class
    def hop_to_it(self, hop_to, electronics=None):
        spawned = [ self.clone() for x in hop_to ]
        for hop, spawn in zip(hop_to, spawned):
            istate = hop["target"]
            weight = hop["weight"]
            stack = hop["stack"]

            spawn.spawn_stack = stack

            # trigger hop
            TrajectoryCum.hop_to_it(spawn, [ hop ], electronics=spawn.electronics)

            # add to total trajectory queue
            self.queue.put(spawn)