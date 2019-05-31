# Copyright 2019 The Cirq Developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import random
from typing import Optional

import numpy as np

from cirq import circuits, study, ops, value
from cirq.work import collector


class PauliStringSampleCollector(collector.SampleCollector):
    """Estimates the energy of a linear combination of Pauli observables."""

    def __init__(self,
                 circuit: circuits.Circuit,
                 samples_per_term: int,
                 terms: value.LinearDict[ops.PauliString],
                 max_samples_per_job: int = 1000):
        """
        Args:
            circuit: Produces the state to be tested.
            terms: The pauli product observables to measure. Their sampled
                expectations will be scaled by their coefficients and their
                dictionary weights, and then added up to produce the final
                result.
            max_samples_per_job: How many samples to request at a time.
        """
        self._circuit = circuit
        self._samples_per_job = max_samples_per_job
        self._terms = [
            # Merge coefficients.
            (ops.PauliString(pauli_string), coef * pauli_string.coefficient)
            for pauli_string, coef in terms.items()
        ]
        self._zeros = collections.defaultdict(lambda: 0)
        self._ones = collections.defaultdict(lambda: 0)
        self._samples_per_term = samples_per_term
        self._total_samples_requested = 0

    def next_job(self) -> Optional[collector.CircuitSampleJob]:
        i = self._total_samples_requested // self._samples_per_term
        if i >= len(self._terms):
            return None
        pauli, _ = self._terms[i]
        remaining = self._samples_per_term * (i + 1
                                              ) - self._total_samples_requested
        amount_to_request = min(remaining, self._samples_per_job)
        self._total_samples_requested += amount_to_request
        return collector.CircuitSampleJob(
            circuit=_circuit_plus_pauli_string_measurements(self._circuit,
                                                            pauli),
            repetitions=amount_to_request,
            id=pauli)

    def on_job_result(self,
                      job: collector.CircuitSampleJob,
                      result: study.TrialResult):
        parities = result.histogram(
            key='out',
            fold_func=lambda bits: np.sum(bits) % 2)
        self._zeros[job.id] += parities[0]
        self._ones[job.id] += parities[1]

    def estimated_energy(self) -> float:
        """Sums up the sampled expectations, weighted by their coefficients."""
        energy = 0
        for pauli_string, coef in self._terms:
            a = self._zeros[pauli_string]
            b = self._ones[pauli_string]
            if a + b:
                energy += coef * (a - b) / (a + b)
        return energy


def _circuit_plus_pauli_string_measurements(circuit: circuits.Circuit,
                                            pauli_string: ops.PauliString
                                            ) -> circuits.Circuit:
    """A circuit measuring the given observable at the end of the given circuit.
    """
    assert pauli_string
    n = len(pauli_string.keys())

    circuit = circuit.copy()
    circuit.append(ops.Moment(pauli_string.to_z_basis_ops()))
    circuit.append(ops.Moment([
        ops.measure(*sorted(pauli_string.keys()), key='out')
    ]))
    return circuit