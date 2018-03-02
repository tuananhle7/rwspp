from pynverse import inversefunc
from torch.autograd import Variable
from util import *

import numpy as np
import torch
import torch.nn as nn


class GenerativeNetwork(nn.Module):
    def __init__(self, num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std):
        super(GenerativeNetwork, self).__init__()
        self.num_clusters_max = len(num_clusters_probs)
        self.num_mixtures = len(mixture_probs)
        self.num_clusters_probs = Variable(torch.Tensor(num_clusters_probs))
        self.mean_1 = nn.Parameter(torch.Tensor([init_mean_1]))
        self.std_1 = std_1
        self.mixture_probs = Variable(torch.Tensor(mixture_probs))
        self.means_2 = Variable(torch.Tensor(means_2))
        self.stds_2 = stds_2
        self.obs_std = obs_std

    def sample_k(self, num_samples):
        if num_samples == 0:
            return Variable(torch.Tensor(0))
        else:
            return torch.multinomial(
                self.num_clusters_probs, num_samples, replacement=True
            ) + 1

    def sample_x_1(self, num_samples):
        if num_samples == 0:
            return Variable(torch.Tensor(0))
        else:
            return self.mean_1 + self.std_1 * Variable(torch.Tensor(num_samples).normal_())

    def sample_z(self, num_samples):
        if num_samples == 0:
            return Variable(torch.Tensor(0))
        else:
            return torch.multinomial(
                self.mixture_probs, num_samples, replacement=True
            )

    def sample_x_20(self, num_samples):
        if num_samples == 0:
            return Variable(torch.Tensor(0))
        else:
            return self.means_2[0] + self.stds_2[0] * Variable(torch.Tensor(num_samples).normal_())

    def sample_x_21(self, num_samples):
        if num_samples == 0:
            return Variable(torch.Tensor(0))
        else:
            return self.means_2[1] + self.stds_2[1] * Variable(torch.Tensor(num_samples).normal_())

    def sample_obs(self, x):
        num_samples = len(x)
        if num_samples == 0:
            return Variable(torch.Tensor(0))
        else:
            return x + self.obs_std * Variable(torch.Tensor(num_samples).normal_())

    def sample(self, num_samples):
        k = self.sample_k(num_samples)

        k_1 = k[k == 1]
        x_1 = self.sample_x_1(len(k_1))
        obs_1 = self.sample_obs(x_1)

        k_2 = k[k == 2]
        z = self.sample_z(len(k_2))

        z_0 = z[z == 0]
        x_20 = self.sample_x_20(len(z_0))
        obs_20 = self.sample_obs(x_20)

        z_1 = z[z == 1]
        x_21 = self.sample_x_21(len(z_1))
        obs_21 = self.sample_obs(x_21)

        return (
            (k_1, x_1, obs_1),
            (k_2[z == 0], z_0, x_20, obs_20),
            (k_2[z == 1], z_1, x_21, obs_21)
        )

    def k_logpdf(self, k):
        num_samples = len(k)
        if num_samples == 0:
            return 0
        else:
            return torch.gather(
                torch.log(self.num_clusters_probs).unsqueeze(0).expand(num_samples, self.num_clusters_max),
                1,
                k.long().unsqueeze(-1) - 1
            ).view(-1)

    def x_1_logpdf(self, x_1):
        num_samples = len(x_1)
        if num_samples == 0:
            return 0
        else:
            return torch.distributions.Normal(
                mean=self.mean_1.expand(num_samples),
                std=self.std_1
            ).log_prob(x_1)

    def z_logpdf(self, z):
        num_samples = len(z)
        if num_samples == 0:
            return 0
        else:
            return torch.gather(
                torch.log(self.mixture_probs).unsqueeze(0).expand(num_samples, self.num_mixtures),
                1,
                z.long().unsqueeze(-1)
            ).view(-1)

    def x_20_logpdf(self, x_20):
        num_samples = len(x_20)
        if num_samples == 0:
            return 0
        else:
            return torch.distributions.Normal(
                mean=self.means_2[0].expand(num_samples),
                std=self.stds_2[0]
            ).log_prob(x_20)

    def x_21_logpdf(self, x_21):
        num_samples = len(x_21)
        if num_samples == 0:
            return 0
        else:
            return torch.distributions.Normal(
                mean=self.means_2[1].expand(num_samples),
                std=self.stds_2[1]
            ).log_prob(x_21)

    def obs_logpdf(self, x, obs):
        num_samples = len(obs)
        if num_samples == 0:
            return 0
        else:
            return torch.distributions.Normal(
                mean=x,
                std=self.obs_std
            ).log_prob(obs)

    def logpdf(self, traces):
        (k_1, x_1, obs_1), (k_20, z_0, x_20, obs_20), (k_21, z_1, x_21, obs_21) = traces
        return (
            self.k_logpdf(k_1) + self.x_1_logpdf(x_1) + self.obs_logpdf(x_1, obs_1),
            self.k_logpdf(k_20) + self.z_logpdf(z_0) + self.x_20_logpdf(x_20) + self.obs_logpdf(x_20, obs_20),
            self.k_logpdf(k_21) + self.z_logpdf(z_1) + self.x_21_logpdf(x_21) + self.obs_logpdf(x_21, obs_21)
        )


class InferenceNetwork(nn.Module):
    def __init__(self, num_clusters_max, num_mixtures):
        super(InferenceNetwork, self).__init__()
        self.num_clusters_max = num_clusters_max
        self.num_mixtures = num_mixtures
        self.obs_to_k_params = nn.Sequential(
            nn.Linear(1, 8),
            nn.Tanh(),
            nn.Linear(8, 8),
            nn.Tanh(),
            nn.Linear(8, num_clusters_max),
            nn.Softmax(dim=1)
        )
        self.obs_k_to_x_mean = nn.Sequential(
            nn.Linear(1, 8),
            nn.Tanh(),
            nn.Linear(8, 8),
            nn.Tanh(),
            nn.Linear(8, 1)
        )
        self.obs_k_to_x_logstd = nn.Sequential(
            nn.Linear(1, 8),
            nn.Tanh(),
            nn.Linear(8, 8),
            nn.Tanh(),
            nn.Linear(8, 1)
        )
        self.obs_k_to_z_params = nn.Sequential(
            nn.Linear(1, 8),
            nn.Tanh(),
            nn.Linear(8, 8),
            nn.Tanh(),
            nn.Linear(8, num_mixtures),
            nn.Softmax(dim=1)
        )
        self.obs_k_z_to_x_mean = nn.Sequential(
            nn.Linear(1 + num_mixtures, 8),
            nn.Tanh(),
            nn.Linear(8, 8),
            nn.Tanh(),
            nn.Linear(8, 1)
        )
        self.obs_k_z_to_x_logstd = nn.Sequential(
            nn.Linear(1 + num_mixtures, 8),
            nn.Tanh(),
            nn.Linear(8, 8),
            nn.Tanh(),
            nn.Linear(8, 1)
        )

    def get_k_params(self, obs):
        if len(obs) == 0:
            return Variable(torch.Tensor(0))
        else:
            return self.obs_to_k_params(obs.unsqueeze(-1))

    def get_x_1_params(self, obs, k):
        if len(obs) == 0:
            return Variable(torch.Tensor(0)), Variable(torch.Tensor(0))
        else:
            mean = self.obs_k_to_x_mean(obs.unsqueeze(-1))
            std = torch.exp(self.obs_k_to_x_logstd(obs.unsqueeze(-1)))
            return mean.squeeze(-1), std.squeeze(-1)

    def get_z_params(self, obs, k):
        if len(obs) == 0:
            return Variable(torch.Tensor(0))
        else:
            return self.obs_k_to_z_params(obs.unsqueeze(-1))

    def get_x_2_params(self, obs, k, z):
        if len(obs) == 0:
            return Variable(torch.Tensor(0)), Variable(torch.Tensor(0))
        else:
            z_one_hot = Variable(torch.zeros(len(z), self.num_mixtures)).scatter_(1, z.long().unsqueeze(-1), 1)
            obs_z = torch.cat([obs.unsqueeze(-1), z_one_hot], dim=1)
            mean = self.obs_k_z_to_x_mean(obs_z)
            std = torch.exp(self.obs_k_z_to_x_logstd(obs_z))
            return mean.squeeze(-1), std.squeeze(-1)

    get_x_20_params = get_x_2_params
    get_x_21_params = get_x_2_params

    def sample_k(self, obs):
        if len(obs) == 0:
            return Variable(torch.Tensor(0))
        else:
            return torch.multinomial(
                self.get_k_params(obs), 1, replacement=True
            ).view(-1) + 1

    def sample_x_1(self, obs, k):
        if len(obs) == 0:
            return Variable(torch.Tensor(0))
        else:
            x_1_mean, x_1_std = self.get_x_1_params(obs, k)
            return x_1_mean + x_1_std * Variable(torch.Tensor(len(x_1_mean)).normal_())

    def sample_z(self, obs, k):
        if len(obs) == 0:
            return Variable(torch.Tensor(0))
        else:
            return torch.multinomial(
                self.get_z_params(obs, k), 1, replacement=True
            ).view(-1)

    def sample_x_2(self, obs, k, z):
        if len(obs) == 0:
            return Variable(torch.Tensor(0))
        else:
            x_2_mean, x_2_std = self.get_x_2_params(obs, k, z)
            return x_2_mean + x_2_std * Variable(torch.Tensor(len(x_2_mean)).normal_())

    sample_x_20 = sample_x_2
    sample_x_21 = sample_x_2

    def sample(self, obs):
        k = self.sample_k(obs)

        k_1 = k[k == 1]
        obs_1 = obs[k == 1]
        x_1 = self.sample_x_1(obs_1, k_1)

        k_2 = k[k == 2]
        obs_2 = obs[k == 2]
        z = self.sample_z(obs_2, k_2)

        z_0 = z[z == 0]
        obs_20 = obs_2[z == 0]
        x_20 = self.sample_x_20(obs_20, k_2, z_0)

        z_1 = z[z == 1]
        obs_21 = obs_2[z == 1]
        x_21 = self.sample_x_21(obs_21, k_2, z_1)

        return (
            (k_1, x_1, obs_1),
            (k_2[z == 0], z_0, x_20, obs_20),
            (k_2[z == 1], z_1, x_21, obs_21)
        )

    def k_logpdf(self, k, obs):
        num_samples = len(k)
        if num_samples == 0:
            return 0
        else:
            return torch.gather(
                torch.log(self.get_k_params(obs)),
                1,
                k.long().unsqueeze(-1) - 1
            ).view(-1)

    def x_1_logpdf(self, x_1, obs, k):
        num_samples = len(x_1)
        if num_samples == 0:
            return 0
        else:
            x_1_mean, x_1_std = self.get_x_1_params(obs, k)
            return torch.distributions.Normal(
                mean=x_1_mean,
                std=x_1_std
            ).log_prob(x_1)

    def z_logpdf(self, z, obs, k):
        num_samples = len(z)
        if num_samples == 0:
            return 0
        else:
            return torch.gather(
                torch.log(self.get_z_params(obs, k)),
                1,
                z.long().unsqueeze(-1)
            ).view(-1)

    def x_2_logpdf(self, x_2, obs, k, z):
        num_samples = len(x_2)
        if num_samples == 0:
            return 0
        else:
            x_2_mean, x_2_std = self.get_x_2_params(obs, k, z)
            return torch.distributions.Normal(
                mean=x_2_mean,
                std=x_2_std
            ).log_prob(x_2)

    x_20_logpdf = x_2_logpdf
    x_21_logpdf = x_2_logpdf

    def logpdf(self, traces):
        (k_1, x_1, obs_1), (k_20, z_0, x_20, obs_20), (k_21, z_1, x_21, obs_21) = traces
        return (
            self.k_logpdf(k_1, obs_1) + self.x_1_logpdf(x_1, obs_1, k_1),
            self.k_logpdf(k_20, obs_20) + self.z_logpdf(z_0, obs_20, k_20) + self.x_20_logpdf(x_20, obs_20, k_20, z_0),
            self.k_logpdf(k_21, obs_21) + self.z_logpdf(z_1, obs_21, k_21) + self.x_21_logpdf(x_21, obs_21, k_21, z_1)
        )


class IWAE(nn.Module):
    def __init__(self, num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std):
        super(IWAE, self).__init__()
        self.generative_network = GenerativeNetwork(num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std)
        self.inference_network = InferenceNetwork(len(num_clusters_probs), len(mixture_probs))

    def elbo(self, obs, num_particles=1):
        num_samples = len(obs)
        result = [None for _ in range(num_samples)]

        for sample_idx in range(num_samples):
            obs_expanded = obs[sample_idx].expand(num_particles)
            traces = self.inference_network.sample(obs_expanded)
            (k_1, x_1, obs_1), (k_20, z_0, x_20, obs_20), (k_21, z_1, x_21, obs_21) = traces
            log_ps = self.generative_network.logpdf(traces)
            log_qs = self.inference_network.logpdf(traces)
            log_weight = torch.cat(list(filter(lambda x: isinstance(x, Variable), map(
                lambda log_p, log_q: log_p - log_q,
                log_ps, log_qs
            ))))
            result[sample_idx] = logsumexp(log_weight) - np.log(num_particles)

        return torch.cat(result)

    def elbo_reinforce(self, obs, num_particles=1):
        num_samples = len(obs)
        result = [None for _ in range(num_samples)]
        elbo = [None for _ in range(num_samples)]

        for sample_idx in range(num_samples):
            obs_expanded = obs[sample_idx].expand(num_particles)
            traces = self.inference_network.sample(obs_expanded)
            (k_1, x_1, obs_1), (k_20, z_0, x_20, obs_20), (k_21, z_1, x_21, obs_21) = traces
            log_ps = self.generative_network.logpdf(traces)
            (
                (log_q_k_1, log_q_x_1),
                (log_q_k_20, log_q_z_0, log_q_x_20),
                (log_q_k_21, log_q_z_1, log_q_x_21)
            ) = (
                (self.inference_network.k_logpdf(k_1, obs_1), self.inference_network.x_1_logpdf(x_1, obs_1, k_1)),
                (self.inference_network.k_logpdf(k_20, obs_20), self.inference_network.z_logpdf(z_0, obs_20, k_20), self.inference_network.x_20_logpdf(x_20, obs_20, k_20, z_0)),
                (self.inference_network.k_logpdf(k_21, obs_21), self.inference_network.z_logpdf(z_1, obs_21, k_21), self.inference_network.x_21_logpdf(x_21, obs_21, k_21, z_1))
            )
            log_qs = (
                log_q_k_1 + log_q_x_1,
                log_q_k_20 + log_q_z_0 + log_q_x_20,
                log_q_k_21 + log_q_z_1 + log_q_x_21
            )
            log_weight = torch.cat(list(filter(lambda x: isinstance(x, Variable), map(
                lambda log_p, log_q: log_p - log_q,
                log_ps, log_qs
            ))))
            elbo[sample_idx] = logsumexp(log_weight) - np.log(num_particles)
            result[sample_idx] = elbo[sample_idx] + elbo[sample_idx].detach() * (
                (torch.sum(log_q_k_1) if isinstance(log_q_k_1, Variable) else 0) +
                (torch.sum(log_q_k_20) + torch.sum(log_q_z_0) if isinstance(log_q_k_20, Variable) else 0) +
                (torch.sum(log_q_k_21) + torch.sum(log_q_z_1) if isinstance(log_q_k_21, Variable) else 0)
            )

        return torch.cat(result), torch.cat(elbo)

    def elbo_vimco(self, obs, num_particles=2):
        num_samples = len(obs)
        result = [None for _ in range(num_samples)]
        elbo = [None for _ in range(num_samples)]

        for sample_idx in range(num_samples):
            obs_expanded = obs[sample_idx].expand(num_particles)
            traces = self.inference_network.sample(obs_expanded)
            (k_1, x_1, obs_1), (k_20, z_0, x_20, obs_20), (k_21, z_1, x_21, obs_21) = traces
            log_ps = self.generative_network.logpdf(traces)
            (
                (log_q_k_1, log_q_x_1),
                (log_q_k_20, log_q_z_0, log_q_x_20),
                (log_q_k_21, log_q_z_1, log_q_x_21)
            ) = (
                (self.inference_network.k_logpdf(k_1, obs_1), self.inference_network.x_1_logpdf(x_1, obs_1, k_1)),
                (self.inference_network.k_logpdf(k_20, obs_20), self.inference_network.z_logpdf(z_0, obs_20, k_20), self.inference_network.x_20_logpdf(x_20, obs_20, k_20, z_0)),
                (self.inference_network.k_logpdf(k_21, obs_21), self.inference_network.z_logpdf(z_1, obs_21, k_21), self.inference_network.x_21_logpdf(x_21, obs_21, k_21, z_1))
            )
            log_qs = (
                log_q_k_1 + log_q_x_1,
                log_q_k_20 + log_q_z_0 + log_q_x_20,
                log_q_k_21 + log_q_z_1 + log_q_x_21
            )
            log_weight = torch.cat(list(filter(lambda x: isinstance(x, Variable), map(
                lambda log_p, log_q: log_p - log_q,
                log_ps, log_qs
            ))))
            elbo[sample_idx] = logsumexp(log_weight) - np.log(num_particles)
            result[sample_idx] = elbo[sample_idx]

            elbo_detached = elbo[sample_idx].detach()
            log_q_discrete = torch.cat(list(filter(lambda x: isinstance(x, Variable), [
                log_q_k_1,
                log_q_k_20 + log_q_z_0,
                log_q_k_21 + log_q_z_1
            ])))
            for i in range(num_particles):
                log_weight_ = log_weight[list(set(range(num_particles)).difference(set([i])))]
                control_variate = logsumexp(torch.cat([log_weight_, torch.mean(log_weight_)])) - np.log(num_particles)
                result[sample_idx] = result[sample_idx] + (elbo_detached - control_variate.detach()) * log_q_discrete[i]

        return torch.cat(result), torch.cat(elbo)

    def forward(self, obs, gradient_estimator, num_particles=2):
        if gradient_estimator == 'reinforce':
            result, elbo = self.elbo_reinforce(obs, num_particles)
            return -torch.mean(result), torch.mean(elbo)
        elif gradient_estimator == 'vimco':
            result, elbo = self.elbo_vimco(obs, num_particles)
            return -torch.mean(result), torch.mean(elbo)
        else:
            raise NotImplementedError


def train_iwae(
    num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
    true_mean_1,
    num_iterations, num_samples, num_particles, gradient_estimator, learning_rate
):
    mean_1_history = np.zeros([num_iterations])
    elbo_history = np.zeros([num_iterations])
    iwae = IWAE(num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std)
    optimizer = torch.optim.Adam(iwae.parameters(), lr=learning_rate)

    for i in range(num_iterations):
        traces = generate_traces(num_samples, num_clusters_probs, true_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std)
        obs = Variable(torch.Tensor([trace[-1] for trace in traces]))

        optimizer.zero_grad()
        loss, elbo = iwae(obs, gradient_estimator, num_particles)

        loss.backward()
        optimizer.step()

        elbo_history[i] = elbo.data[0]
        mean_1_history[i] = iwae.generative_network.mean_1.data[0]
        if i % 100 == 0:
            print('Iteration {}'.format(i))

    return elbo_history, iwae, mean_1_history


class RWS(nn.Module):
    def __init__(
        self, num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        init_wake_phi_anneal_factor=None, wake_phi_ess_threshold=None
    ):
        super(RWS, self).__init__()
        self.generative_network = GenerativeNetwork(num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std)
        self.inference_network = InferenceNetwork(len(num_clusters_probs), len(mixture_probs))
        self.anneal_factor = init_wake_phi_anneal_factor
        self.ess_threshold = wake_phi_ess_threshold

    def ess(self, log_weight, anneal_factor, particles_dim=0):
        return torch.exp(
            2 * logsumexp(log_weight * anneal_factor, dim=particles_dim) -
            logsumexp(2 * log_weight * anneal_factor, dim=particles_dim)
        )

    def update_anneal_factor_greedy(self):
        self.anneal_factor = (1 + self.anneal_factor) / 2

    def update_anneal_factor_bs(self, log_weight):
        num_particles = log_weight.size(-1)
        func = lambda a: torch.mean(self.ess(log_weight, float(a))).data[0]
        self.anneal_factor = float(inversefunc(func, y_values=self.ess_threshold * num_particles, domain=[0, 1]))

    def wake_theta(self, obs, num_particles=1):
        num_samples = len(obs)
        result = [None for _ in range(num_samples)]

        for sample_idx in range(num_samples):
            obs_expanded = obs[sample_idx].expand(num_particles)
            traces = self.inference_network.sample(obs_expanded)
            traces = tuple(map(lambda x: tuple(map(lambda y: y.detach(), x)), traces))
            (k_1, x_1, obs_1), (k_20, z_0, x_20, obs_20), (k_21, z_1, x_21, obs_21) = traces
            log_ps = self.generative_network.logpdf(traces)
            log_qs = self.inference_network.logpdf(traces)
            log_weight = torch.cat(list(filter(lambda x: isinstance(x, Variable), map(
                lambda log_p, log_q: log_p - log_q,
                log_ps, log_qs
            ))))
            result[sample_idx] = logsumexp(log_weight) - np.log(num_particles)

        return -torch.cat(result)

    def sleep_phi(self, num_samples):
        traces = self.generative_network.sample(num_samples)
        traces = tuple(map(lambda x: tuple(map(lambda y: y.detach(), x)), traces))
        return -torch.cat(list(filter(
            lambda x: isinstance(x, Variable),
            self.inference_network.logpdf(traces)
        )))

    def wake_phi(self, obs, num_particles=1):
        num_samples = len(obs)
        result = [None for _ in range(num_samples)]

        for sample_idx in range(num_samples):
            obs_expanded = obs[sample_idx].expand(num_particles)
            traces = self.inference_network.sample(obs_expanded)
            traces = tuple(map(lambda x: tuple(map(lambda y: y.detach(), x)), traces))
            (k_1, x_1, obs_1), (k_20, z_0, x_20, obs_20), (k_21, z_1, x_21, obs_21) = traces
            log_ps = self.generative_network.logpdf(traces)
            log_qs = self.inference_network.logpdf(traces)
            log_weight = torch.cat(list(filter(lambda x: isinstance(x, Variable), map(
                lambda log_p, log_q: log_p - log_q,
                log_ps, log_qs
            ))))

            if self.anneal_factor is None:
                normalized_weight = torch.exp(lognormexp(log_weight))
            else:
                if torch.mean(self.ess(log_weight, self.anneal_factor)).data[0] < self.ess_threshold * num_particles:
                    self.update_anneal_factor_bs(log_weight)
                else:
                    self.update_anneal_factor_greedy()
                normalized_weight = torch.exp(lognormexp(log_weight * self.anneal_factor))

            log_q = torch.cat(list(filter(lambda x: isinstance(x, Variable), log_qs)))
            result[sample_idx] = -torch.sum(normalized_weight.detach() * log_q)

        return torch.cat(result)

    def forward(self, mode, obs=None, num_particles=None, num_samples=None):
        if mode == 'wake_theta':
            return torch.mean(self.wake_theta(obs, num_particles))
        elif mode == 'sleep_phi':
            return torch.mean(self.sleep_phi(num_samples))
        elif mode == 'wake_phi':
            return torch.mean(self.wake_phi(obs, num_particles))
        else:
            raise NotImplementedError()


def train_rws(
    num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
    true_mean_1,
    sleep_phi, wake_phi, num_samples, num_particles,
    theta_learning_rate, phi_learning_rate,
    num_iterations, anneal_wake_phi=False, init_anneal_factor=None, ess_threshold=None, sleep_num_samples=None
):
    if (not sleep_phi) and (not wake_phi):
        raise AttributeError('Must have at least one of sleep_phi or wake_phi phases')
    if (not wake_phi) and anneal_wake_phi:
        raise AttributeError('Must have wake-phi phase in order to be able to anneal it')

    mean_1_history = np.zeros([num_iterations])

    wake_theta_loss_history = np.zeros([num_iterations])
    if sleep_phi:
        sleep_phi_loss_history = np.zeros([num_iterations])
    if wake_phi:
        wake_phi_loss_history = np.zeros([num_iterations])

    if anneal_wake_phi:
        anneal_factor_history = np.zeros([num_iterations])
        rws = RWS(
            num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
            init_anneal_factor, ess_threshold
        )
    else:
        rws = RWS(num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std)

    theta_optimizer = torch.optim.Adam(rws.generative_network.parameters(), lr=theta_learning_rate)
    phi_optimizer = torch.optim.Adam(rws.inference_network.parameters(), lr=phi_learning_rate)

    for i in range(num_iterations):
        traces = generate_traces(num_samples, num_clusters_probs, true_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std)
        obs = Variable(torch.Tensor([trace[-1] for trace in traces]))

        # Wake theta
        theta_optimizer.zero_grad()
        loss = rws('wake_theta', obs=obs, num_particles=num_particles)
        loss.backward()
        theta_optimizer.step()
        wake_theta_loss_history[i] = loss.data[0]

        # Sleep phi
        if sleep_phi:
            phi_optimizer.zero_grad()
            loss = rws('sleep_phi', num_samples=sleep_num_samples)
            loss.backward()
            phi_optimizer.step()
            sleep_phi_loss_history[i] = loss.data[0]

        # Wake phi
        if wake_phi:
            phi_optimizer.zero_grad()
            loss = rws('wake_phi', obs=obs, num_particles=num_particles)
            loss.backward()
            phi_optimizer.step()
            wake_phi_loss_history[i] = loss.data[0]

            if anneal_wake_phi:
                anneal_factor_history[i] = rws.anneal_factor

        mean_1_history[i] = rws.generative_network.mean_1.data[0]

        if i % 100 == 0:
            print('Iteration {}'.format(i))

    result = (mean_1_history, wake_theta_loss_history)

    if sleep_phi:
        result = result + (sleep_phi_loss_history,)
    else:
        result = result + (None,)

    if wake_phi:
        result = result + (wake_phi_loss_history,)
    else:
        result = result + (None,)

    if anneal_wake_phi:
        result = result + (anneal_factor_history,)
    else:
        result = result + (None,)

    return result


def main():
    num_clusters_probs = [0.5, 0.5]
    true_mean_1 = 0
    std_1 = 1
    mixture_probs = [0.5, 0.5]
    means_2 = [-5, 5]
    stds_2 = [1, 1]
    obs_std = 1

    init_mean_1 = 2

    num_iterations = 10000
    learning_rate = 0.001

    # VAE
    vae_num_samples = 100
    gradient_estimator = 'reinforce'

    vae_reinforce_elbo_history, vae_reinforce, vae_reinforce_mean_1_history = train_iwae(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        num_iterations, vae_num_samples, 1, gradient_estimator, learning_rate
    )
    for [data, filename] in zip(
        [vae_reinforce_elbo_history, vae_reinforce_mean_1_history],
        ['vae_reinforce_elbo_history.npy', 'vae_reinforce_mean_1_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    # IWAE
    iwae_num_samples = 100
    iwae_num_particles = 10

    ## Reinforce
    gradient_estimator = 'reinforce'

    iwae_reinforce_elbo_history, iwae_reinforce, iwae_reinforce_mean_1_history = train_iwae(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        num_iterations, iwae_num_samples, iwae_num_particles, gradient_estimator, learning_rate
    )
    for [data, filename] in zip(
        [iwae_reinforce_elbo_history, iwae_reinforce_mean_1_history],
        ['iwae_reinforce_elbo_history.npy', 'iwae_reinforce_mean_1_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    ## VIMCO
    gradient_estimator = 'vimco'

    iwae_vimco_elbo_history, iwae_vimco, iwae_vimco_mean_1_history = train_iwae(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        num_iterations, iwae_num_samples, iwae_num_particles, gradient_estimator, learning_rate
    )
    for [data, filename] in zip(
        [iwae_vimco_elbo_history, iwae_vimco_mean_1_history],
        ['iwae_vimco_elbo_history.npy', 'iwae_vimco_mean_1_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    # WS
    theta_learning_rate = learning_rate
    phi_learning_rate = learning_rate
    ws_num_samples = 100
    ws_sleep_num_samples = 100

    sleep_phi = True
    wake_phi = False

    ws1_mean_1_history, ws1_wake_theta_loss_history, ws1_sleep_phi_loss_history, _, _ = train_rws(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        sleep_phi, wake_phi, ws_num_samples, 1,
        theta_learning_rate, phi_learning_rate,
        num_iterations, sleep_num_samples=ws_sleep_num_samples
    )
    for [data, filename] in zip(
        [ws1_mean_1_history, ws1_wake_theta_loss_history, ws1_sleep_phi_loss_history],
        ['ws1_mean_1_history.npy', 'ws1_wake_theta_loss_history.npy', 'ws1_sleep_phi_loss_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    # RWS
    rws_num_particles = 10
    rws_num_samples = 100
    rws_sleep_num_samples = 100

    ## WS
    sleep_phi = True
    wake_phi = False

    ws_mean_1_history, ws_wake_theta_loss_history, ws_sleep_phi_loss_history, _, _ = train_rws(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        sleep_phi, wake_phi, rws_num_samples, rws_num_particles,
        theta_learning_rate, phi_learning_rate,
        num_iterations, sleep_num_samples=rws_sleep_num_samples
    )
    for [data, filename] in zip(
        [ws_mean_1_history, ws_wake_theta_loss_history, ws_sleep_phi_loss_history],
        ['ws_mean_1_history.npy', 'ws_wake_theta_loss_history.npy', 'ws_sleep_phi_loss_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    ## WW
    sleep_phi = False
    wake_phi = True
    ww_mean_1_history, ww_wake_theta_loss_history, _, ww_wake_phi_loss_history, _ = train_rws(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        sleep_phi, wake_phi, rws_num_samples, rws_num_particles,
        theta_learning_rate, phi_learning_rate,
        num_iterations
    )
    for [data, filename] in zip(
        [ww_mean_1_history, ww_wake_theta_loss_history, ww_wake_phi_loss_history],
        ['ww_mean_1_history.npy', 'ww_wake_theta_loss_history.npy', 'ww_wake_phi_loss_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    ## WSW
    sleep_phi = True
    wake_phi = True
    wsw_mean_1_history, wsw_wake_theta_loss_history, wsw_sleep_phi_loss_history, wsw_wake_phi_loss_history, _ = train_rws(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        sleep_phi, wake_phi, rws_num_samples, rws_num_particles,
        theta_learning_rate, phi_learning_rate,
        num_iterations, sleep_num_samples=rws_sleep_num_samples
    )
    for [data, filename] in zip(
        [wsw_mean_1_history, wsw_wake_theta_loss_history, wsw_sleep_phi_loss_history, wsw_wake_phi_loss_history],
        ['wsw_mean_1_history.npy', 'wsw_wake_theta_loss_history.npy', 'wsw_sleep_phi_loss_history.npy', 'wsw_wake_phi_loss_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    ## WaW
    sleep_phi = False
    wake_phi = True
    anneal_wake_phi = True
    init_anneal_factor = 0
    ess_threshold = 0.90

    waw_mean_1_history, waw_wake_theta_loss_history, _, waw_wake_phi_loss_history, waw_anneal_factor_history = train_rws(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        sleep_phi, wake_phi, rws_num_samples, rws_num_particles,
        theta_learning_rate, phi_learning_rate,
        num_iterations, anneal_wake_phi, init_anneal_factor, ess_threshold
    )
    for [data, filename] in zip(
        [waw_mean_1_history, waw_wake_theta_loss_history, waw_wake_phi_loss_history, waw_anneal_factor_history],
        ['waw_mean_1_history.npy', 'waw_wake_theta_loss_history.npy', 'waw_wake_phi_loss_history.npy', 'waw_anneal_factor_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))

    ## WSaW
    sleep_phi = True
    wake_phi = True
    anneal_wake_phi = True
    init_anneal_factor = 0
    ess_threshold = 0.90

    wsaw_mean_1_history, wsaw_wake_theta_loss_history, wsaw_sleep_phi_loss_history, wsaw_wake_phi_loss_history, wsaw_anneal_factor_history = train_rws(
        num_clusters_probs, init_mean_1, std_1, mixture_probs, means_2, stds_2, obs_std,
        true_mean_1,
        sleep_phi, wake_phi, rws_num_samples, rws_num_particles,
        theta_learning_rate, phi_learning_rate,
        num_iterations, anneal_wake_phi, init_anneal_factor, ess_threshold, sleep_num_samples=rws_sleep_num_samples
    )
    for [data, filename] in zip(
        [wsaw_mean_1_history, wsaw_wake_theta_loss_history, wsaw_sleep_phi_loss_history, wsaw_wake_phi_loss_history, wsaw_anneal_factor_history],
        ['wsaw_mean_1_history.npy', 'wsaw_wake_theta_loss_history.npy', 'wsaw_sleep_phi_loss_history.npy', 'wsaw_wake_phi_loss_history.npy', 'wsaw_anneal_factor_history.npy']
    ):
        np.save(filename, data)
        print('Saved to {}'.format(filename))


if __name__ == '__main__':
    main()
