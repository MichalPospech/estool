import numpy as np
import scipy as scp


def compute_ranks(x):
    """
    Returns ranks in [0, len(x))
    Note: This is different from scipy.stats.rankdata, which returns ranks in [1, len(x)].
    (https://github.com/openai/evolution-strategies-starter/blob/master/es_distributed/es.py)
    """
    assert x.ndim == 1
    ranks = np.empty(len(x), dtype=int)
    ranks[x.argsort()] = np.arange(len(x))
    return ranks


def compute_centered_ranks(x):
    """
    https://github.com/openai/evolution-strategies-starter/blob/master/es_distributed/es.py
    """
    y = compute_ranks(x.ravel()).reshape(x.shape).astype(np.float32)
    y /= x.size - 1
    y -= 0.5
    return y


def compute_weight_decay(weight_decay, model_param_list):
    model_param_grid = np.array(model_param_list)
    return -weight_decay * np.mean(model_param_grid * model_param_grid, axis=1)


# adopted from:
# https://github.com/openai/evolution-strategies-starter/blob/master/es_distributed/optimizers.py


class Optimizer(object):
    def __init__(self, pi, epsilon=1e-08):
        self.pi = pi
        self.dim = pi.num_params
        self.epsilon = epsilon
        self.t = 0

    def update(self, globalg):
        self.t += 1
        step = self._compute_step(globalg)
        theta = self.pi.mu
        ratio = np.linalg.norm(step) / (np.linalg.norm(theta) + self.epsilon)
        self.pi.mu = theta + step
        return ratio

    def _compute_step(self, globalg):
        raise NotImplementedError


class BasicSGD(Optimizer):
    def __init__(self, pi, stepsize):
        Optimizer.__init__(self, pi)
        self.stepsize = stepsize

    def _compute_step(self, globalg):
        step = -self.stepsize * globalg
        return step


class SGD(Optimizer):
    def __init__(self, pi, stepsize, momentum=0.9):
        Optimizer.__init__(self, pi)
        self.v = np.zeros(self.dim, dtype=np.float32)
        self.stepsize, self.momentum = stepsize, momentum

    def _compute_step(self, globalg):
        self.v = self.momentum * self.v + (1.0 - self.momentum) * globalg
        step = -self.stepsize * self.v
        return step


class Adam(Optimizer):
    def __init__(self, pi, stepsize, beta1=0.99, beta2=0.999):
        Optimizer.__init__(self, pi)
        self.stepsize = stepsize
        self.beta1 = beta1
        self.beta2 = beta2
        self.m = np.zeros(self.dim, dtype=np.float32)
        self.v = np.zeros(self.dim, dtype=np.float32)

    def _compute_step(self, globalg):
        a = (
            self.stepsize
            * np.sqrt(1 - self.beta2 ** self.t)
            / (1 - self.beta1 ** self.t)
        )
        self.m = self.beta1 * self.m + (1 - self.beta1) * globalg
        self.v = self.beta2 * self.v + (1 - self.beta2) * (globalg * globalg)
        step = -a * self.m / (np.sqrt(self.v) + self.epsilon)
        return step


class SimpleAdam:
    def __init__(self, stepsize, num_params, beta1=0.99, beta2=0.999):
        self.stepsize = stepsize
        self.beta1 = beta1
        self.beta2 = beta2
        self.m = np.zeros(num_params, dtype=np.float32)
        self.v = np.zeros(num_params, dtype=np.float32)
        self.t = 0
        self.epsilon = 1e-08

    def compute_step(self, gradient):
        self.t += 1
        a = (
            self.stepsize
            * np.sqrt(1 - self.beta2 ** self.t)
            / (1 - self.beta1 ** self.t)
        )
        self.m = self.beta1 * self.m + (1 - self.beta1) * gradient
        self.v = self.beta2 * self.v + (1 - self.beta2) * (gradient * gradient)
        step = -a * self.m / (np.sqrt(self.v) + self.epsilon)
        return step


class SimpleSGD:
    def __init__(self, stepsize):
        self.stepsize = stepsize

    def compute_step(self, gradient):
        step = -self.stepsize * gradient
        return step


class SimpleSGDMomentum:
    def __init__(self, stepsize, num_params, momentum=0.9):
        self.v = np.zeros(num_params, dtype=np.float32)
        self.stepsize, self.momentum = stepsize, momentum

    def compute_step(self, gradient):
        self.v = self.momentum * self.v + (1.0 - self.momentum) * gradient
        step = -self.stepsize * self.v
        return step


def create_optimizer(parameter_dict, num_params):
    params = parameter_dict.copy()
    name = params["name"]
    params.pop("name")
    opt = None
    if name == "sgd":
        opt = SimpleSGD(**params)
    elif name == "adam":
        opt = SimpleAdam(num_params=num_params, **params)
    elif name == "sgdm":
        opt = SimpleSGDMomentum(num_params=num_params, **params)
    else:
        raise ValueError(f"Unsupported optimizer {name}")
    return opt


class CMAES:
    """CMA-ES wrapper."""

    def __init__(
        self,
        num_params,  # number of model parameters
        sigma_init=0.10,  # initial standard deviation
        popsize=255,  # population size
        weight_decay=0.01,
    ):  # weight decay coefficient

        self.num_params = num_params
        self.sigma_init = sigma_init
        self.popsize = popsize
        self.weight_decay = weight_decay
        self.solutions = None

        import cma

        self.es = cma.CMAEvolutionStrategy(
            self.num_params * [0],
            self.sigma_init,
            {
                "popsize": self.popsize,
            },
        )

    def rms_stdev(self):
        sigma = self.es.result[6]
        return np.mean(np.sqrt(sigma * sigma))

    def ask(self):
        """returns a list of parameters"""
        self.solutions = np.array(self.es.ask())
        return self.solutions

    def tell(self, reward_table_result, *_):
        reward_table = -np.array(reward_table_result)
        if self.weight_decay > 0:
            l2_decay = compute_weight_decay(self.weight_decay, self.solutions)
            reward_table += l2_decay
        self.es.tell(
            self.solutions, (reward_table).tolist()
        )  # convert minimizer to maximizer.

    def current_param(self):
        return self.es.result[5]  # mean solution, presumably better with noise

    def set_mu(self, mu):
        pass

    def best_param(self):
        return self.es.result[0]  # best evaluated solution

    def result(
        self,
    ):  # return best params so far, along with historically best reward, curr reward, sigma
        r = self.es.result
        return (r[0], -r[1], -r[1], r[6])

    def init(self, evaluator=None):
        pass


class SimpleGA:
    """Simple Genetic Algorithm."""

    def __init__(
        self,
        num_params,  # number of model parameters
        sigma_init=0.1,  # initial standard deviation
        sigma_decay=0.999,  # anneal standard deviation
        sigma_limit=0.01,  # stop annealing if less than this
        popsize=256,  # population size
        elite_ratio=0.1,  # percentage of the elites
        forget_best=False,  # forget the historical best elites
        weight_decay=0.01,  # weight decay coefficient
    ):

        self.num_params = num_params
        self.sigma_init = sigma_init
        self.sigma_decay = sigma_decay
        self.sigma_limit = sigma_limit
        self.popsize = popsize

        self.elite_ratio = elite_ratio
        self.elite_popsize = int(self.popsize * self.elite_ratio)

        self.sigma = self.sigma_init
        self.elite_params = np.zeros((self.elite_popsize, self.num_params))
        self.elite_rewards = np.zeros(self.elite_popsize)
        self.best_param = np.zeros(self.num_params)
        self.best_reward = 0
        self.first_iteration = True
        self.forget_best = forget_best
        self.weight_decay = weight_decay

    def rms_stdev(self):
        return self.sigma  # same sigma for all parameters.

    def ask(self):
        """returns a list of parameters"""
        self.epsilon = np.random.randn(self.popsize, self.num_params) * self.sigma
        solutions = []

        def mate(a, b):
            c = np.copy(a)
            idx = np.where(np.random.rand((c.size)) > 0.5)
            c[idx] = b[idx]
            return c

        elite_range = range(self.elite_popsize)
        for i in range(self.popsize):
            idx_a = np.random.choice(elite_range)
            idx_b = np.random.choice(elite_range)
            child_params = mate(self.elite_params[idx_a], self.elite_params[idx_b])
            solutions.append(child_params + self.epsilon[i])

        solutions = np.array(solutions)
        self.solutions = solutions

        return solutions

    def tell(self, reward_table_result, *_):
        # input must be a numpy float array
        assert (
            len(reward_table_result) == self.popsize
        ), "Inconsistent reward_table size reported."

        reward_table = np.array(reward_table_result)

        if self.weight_decay > 0:
            l2_decay = compute_weight_decay(self.weight_decay, self.solutions)
            reward_table += l2_decay

        if self.forget_best or self.first_iteration:
            reward = reward_table
            solution = self.solutions
        else:
            reward = np.concatenate([reward_table, self.elite_rewards])
            solution = np.concatenate([self.solutions, self.elite_params])

        idx = np.argsort(reward)[::-1][0 : self.elite_popsize]

        self.elite_rewards = reward[idx]
        self.elite_params = solution[idx]

        self.curr_best_reward = self.elite_rewards[0]

        if self.first_iteration or (self.curr_best_reward > self.best_reward):
            self.first_iteration = False
            self.best_reward = self.elite_rewards[0]
            self.best_param = np.copy(self.elite_params[0])

        if self.sigma > self.sigma_limit:
            self.sigma *= self.sigma_decay

    def current_param(self):
        return self.elite_params[0]

    def set_mu(self, mu):
        pass

    def best_param(self):
        return self.best_param

    def result(
        self,
    ):  # return best params so far, along with historically best reward, curr reward, sigma
        return (self.best_param, self.best_reward, self.curr_best_reward, self.sigma)

    def init(self, evaluator=None):
        pass


class OpenES:
    """ Basic Version of OpenAI Evolution Strategies."""

    def __init__(
        self,
        num_params,  # number of model parameters
        optimizer,
        sigma_init=0.1,  # initial standard deviation
        sigma_decay=0.999,  # anneal standard deviation
        sigma_limit=0.01,  # stop annealing if less than this
        learning_rate=0.01,  # learning rate for standard deviation
        learning_rate_decay=0.9999,  # annealing the learning rate
        learning_rate_limit=0.001,  # stop annealing learning rate
        popsize=256,  # population size
        antithetic=False,  # whether to use antithetic sampling
        weight_decay=0.01,  # weight decay coefficient
        rank_fitness=True,  # use rank rather than fitness numbers
        forget_best=True,
    ):  # forget historical best

        self.num_params = num_params
        self.sigma_decay = sigma_decay
        self.sigma = sigma_init
        self.sigma_init = sigma_init
        self.sigma_limit = sigma_limit
        self.learning_rate = learning_rate
        self.learning_rate_decay = learning_rate_decay
        self.learning_rate_limit = learning_rate_limit
        self.popsize = popsize
        self.antithetic = antithetic
        if self.antithetic:
            assert self.popsize % 2 == 0, "Population size must be even"
            self.half_popsize = int(self.popsize / 2)

        self.reward = np.zeros(self.popsize)
        self.mu = np.zeros(self.num_params)
        self.best_mu = np.zeros(self.num_params)
        self.best_reward = 0
        self.first_interation = True
        self.forget_best = forget_best
        self.weight_decay = weight_decay
        self.rank_fitness = rank_fitness
        if self.rank_fitness:
            self.forget_best = True  # always forget the best one if we rank
        # choose optimizer
        self.optimizer = create_optimizer(optimizer, num_params)

    def rms_stdev(self):
        sigma = self.sigma
        return np.mean(np.sqrt(sigma * sigma))

    def ask(self):
        """returns a list of parameters"""
        # antithetic sampling
        if self.antithetic:
            self.epsilon_half = np.random.randn(self.half_popsize, self.num_params)
            self.epsilon = np.concatenate([self.epsilon_half, -self.epsilon_half])
        else:
            self.epsilon = np.random.randn(self.popsize, self.num_params)

        self.solutions = self.mu.reshape(1, self.num_params) + self.epsilon * self.sigma

        return self.solutions

    def tell(self, reward_table_result, *_):
        # input must be a numpy float array
        assert (
            len(reward_table_result) == self.popsize
        ), "Inconsistent reward_table size reported."

        reward = np.array(reward_table_result)

        if self.rank_fitness:
            reward = compute_centered_ranks(reward)

        if self.weight_decay > 0:
            l2_decay = compute_weight_decay(self.weight_decay, self.solutions)
            reward += l2_decay

        idx = np.argsort(reward)[::-1]

        best_reward = reward[idx[0]]
        best_mu = self.solutions[idx[0]]

        self.curr_best_reward = best_reward
        self.curr_best_mu = best_mu

        if self.first_interation:
            self.first_interation = False
            self.best_reward = self.curr_best_reward
            self.best_mu = best_mu
        else:
            if self.forget_best or (self.curr_best_reward > self.best_reward):
                self.best_mu = best_mu
                self.best_reward = self.curr_best_reward

        # main bit:
        # standardize the rewards to have a gaussian distribution
        normalized_reward = compute_centered_ranks(reward)
        gradient = (
            1.0
            / (self.popsize * self.sigma)
            * np.dot(self.epsilon.T, normalized_reward)
        )

        self.mu -= self.optimizer.compute_step(gradient)

        # adjust sigma according to the adaptive sigma calculation
        if self.sigma > self.sigma_limit:
            self.sigma *= self.sigma_decay

        if self.learning_rate > self.learning_rate_limit:
            self.learning_rate *= self.learning_rate_decay

    def current_param(self):
        return self.curr_best_mu

    def set_mu(self, mu):
        self.mu = np.array(mu)

    def best_param(self):
        return self.best_mu

    def result(
        self,
    ):  # return best params so far, along with historically best reward, curr reward, sigma
        return (self.best_mu, self.best_reward, self.curr_best_reward, self.sigma)

    def init(self, evaluator=None):
        pass


class PEPG:
    """Extension of PEPG with bells and whistles."""

    def __init__(
        self,
        num_params,  # number of model parameters
        sigma_init=0.10,  # initial standard deviation
        sigma_alpha=0.20,  # learning rate for standard deviation
        sigma_decay=0.999,  # anneal standard deviation
        sigma_limit=0.01,  # stop annealing if less than this
        sigma_max_change=0.2,  # clips adaptive sigma to 20%
        learning_rate=0.01,  # learning rate for standard deviation
        learning_rate_decay=0.9999,  # annealing the learning rate
        learning_rate_limit=0.01,  # stop annealing learning rate
        elite_ratio=0,  # if > 0, then ignore learning_rate
        popsize=256,  # population size
        average_baseline=True,  # set baseline to average of batch
        weight_decay=0.01,  # weight decay coefficient
        rank_fitness=True,  # use rank rather than fitness numbers
        forget_best=True,
    ):  # don't keep the historical best solution

        self.num_params = num_params
        self.sigma_init = sigma_init
        self.sigma_alpha = sigma_alpha
        self.sigma_decay = sigma_decay
        self.sigma_limit = sigma_limit
        self.sigma_max_change = sigma_max_change
        self.learning_rate = learning_rate
        self.learning_rate_decay = learning_rate_decay
        self.learning_rate_limit = learning_rate_limit
        self.popsize = popsize
        self.average_baseline = average_baseline
        if self.average_baseline:
            assert self.popsize % 2 == 0, "Population size must be even"
            self.batch_size = int(self.popsize / 2)
        else:
            assert self.popsize & 1, "Population size must be odd"
            self.batch_size = int((self.popsize - 1) / 2)

        # option to use greedy es method to select next mu, rather than using drift param
        self.elite_ratio = elite_ratio
        self.elite_popsize = int(self.popsize * self.elite_ratio)
        self.use_elite = False
        if self.elite_popsize > 0:
            self.use_elite = True

        self.forget_best = forget_best
        self.batch_reward = np.zeros(self.batch_size * 2)
        self.mu = np.zeros(self.num_params)
        self.sigma = np.ones(self.num_params) * self.sigma_init
        self.curr_best_mu = np.zeros(self.num_params)
        self.best_mu = np.zeros(self.num_params)
        self.best_reward = 0
        self.first_interation = True
        self.weight_decay = weight_decay
        self.rank_fitness = rank_fitness
        if self.rank_fitness:
            self.forget_best = True  # always forget the best one if we rank
        # choose optimizer
        self.optimizer = Adam(self, learning_rate)

    def rms_stdev(self):
        sigma = self.sigma
        return np.mean(np.sqrt(sigma * sigma))

    def ask(self):
        """returns a list of parameters"""
        # antithetic sampling
        self.epsilon = np.random.randn(
            self.batch_size, self.num_params
        ) * self.sigma.reshape(1, self.num_params)
        self.epsilon_full = np.concatenate([self.epsilon, -self.epsilon])
        if self.average_baseline:
            epsilon = self.epsilon_full
        else:
            # first population is mu, then positive epsilon, then negative epsilon
            epsilon = np.concatenate(
                [np.zeros((1, self.num_params)), self.epsilon_full]
            )
        solutions = self.mu.reshape(1, self.num_params) + epsilon
        self.solutions = solutions
        return solutions

    def tell(self, reward_table_result, *_):
        # input must be a numpy float array
        assert (
            len(reward_table_result) == self.popsize
        ), "Inconsistent reward_table size reported."

        reward_table = np.array(reward_table_result)

        if self.rank_fitness:
            reward_table = compute_centered_ranks(reward_table)

        if self.weight_decay > 0:
            l2_decay = compute_weight_decay(self.weight_decay, self.solutions)
            reward_table += l2_decay

        reward_offset = 1
        if self.average_baseline:
            b = np.mean(reward_table)
            reward_offset = 0
        else:
            b = reward_table[0]  # baseline

        reward = reward_table[reward_offset:]
        if self.use_elite:
            idx = np.argsort(reward)[::-1][0 : self.elite_popsize]
        else:
            idx = np.argsort(reward)[::-1]

        best_reward = reward[idx[0]]
        if best_reward > b or self.average_baseline:
            best_mu = self.mu + self.epsilon_full[idx[0]]
            best_reward = reward[idx[0]]
        else:
            best_mu = self.mu
            best_reward = b

        self.curr_best_reward = best_reward
        self.curr_best_mu = best_mu

        if self.first_interation:
            self.sigma = np.ones(self.num_params) * self.sigma_init
            self.first_interation = False
            self.best_reward = self.curr_best_reward
            self.best_mu = best_mu
        else:
            if self.forget_best or (self.curr_best_reward > self.best_reward):
                self.best_mu = best_mu
                self.best_reward = self.curr_best_reward

        # short hand
        epsilon = self.epsilon
        sigma = self.sigma

        # update the mean

        # move mean to the average of the best idx means
        if self.use_elite:
            self.mu += self.epsilon_full[idx].mean(axis=0)
        else:
            rT = reward[: self.batch_size] - reward[self.batch_size :]
            change_mu = np.dot(rT, epsilon)/2
            self.optimizer.stepsize = self.learning_rate
            update_ratio = self.optimizer.update(
                -change_mu
            )  # adam, rmsprop, momentum, etc.
            # self.mu += (change_mu * self.learning_rate) # normal SGD method

        # adaptive sigma
        # normalization
        if self.sigma_alpha > 0:
            stdev_reward = 1.0
            if not self.rank_fitness:
                stdev_reward = reward.std()
            S = (
                epsilon * epsilon - (sigma * sigma).reshape(1, self.num_params)
            ) / sigma.reshape(1, self.num_params)
            reward_avg = (reward[: self.batch_size] + reward[self.batch_size :]) / 2.0
            rS = reward_avg - b
            delta_sigma = np.dot(rS,S) 

            # adjust sigma according to the adaptive sigma calculation
            # for stability, don't let sigma move more than 10% of orig value
            change_sigma = self.sigma_alpha * delta_sigma
            change_sigma = np.minimum(change_sigma, self.sigma_max_change * self.sigma)
            change_sigma = np.maximum(change_sigma, -self.sigma_max_change * self.sigma)
            self.sigma += change_sigma

        if self.sigma_decay < 1:
            self.sigma[self.sigma > self.sigma_limit] *= self.sigma_decay

        if (
            self.learning_rate_decay < 1
            and self.learning_rate > self.learning_rate_limit
        ):
            self.learning_rate *= self.learning_rate_decay

    def current_param(self):
        return self.curr_best_mu

    def set_mu(self, mu):
        self.mu = np.array(mu)

    def best_param(self):
        return self.best_mu

    def result(
        self,
    ):  # return best params so far, along with historically best reward, curr reward, sigma
        return (self.best_mu, self.best_reward, self.curr_best_reward, self.sigma)

    def init(self, evaluator=None):
        pass


class NSAbstract:
    def __init__(
        self,
        num_params,  # number of model parameters
        optimizer_params,
        weight,
        sigma_init=0.1,  # initial standard deviation
        popsize=256,  # population size
        metapopulation_size=10,
        k=5,
        antithetic=False,  # whether to use antithetic sampling
    ):
        self.optimizers = [
            create_optimizer(optimizer_params, num_params)
            for _ in range(metapopulation_size)
        ]
        self.num_params = num_params
        self.sigma = sigma_init
        self.k = k
        self.popsize = popsize
        self.metapopulation_size = metapopulation_size
        self.antithetic = antithetic
        if self.antithetic:
            assert self.popsize % 2 == 0, "Population size must be even"
            self.half_popsize = int(self.popsize / 2)

        self.best_reward = 0
        self.best = None
        self.weight = weight

    def rms_stdev(self):
        sigma = self.sigma
        return np.mean(np.sqrt(sigma * sigma))

    def get_gradient(self, novelties, normalized_reward):
        weights = novelties * self.weight + normalized_reward
        scale = self.sigma * self.popsize
        unscaled_update = np.dot(self.epsilon.T, weights)
        return unscaled_update / scale

    def calculate_novelty(self, characteristic):
        distances = []
        for solution_characteristics in self.characteristics:
            if solution_characteristics == characteristic:
                distances.append(0)
                continue
            distances = scp.spatial.distance.cdist(solution_characteristics, characteristic)
            mean_distance = np.mean(distances)
            distances.append(mean_distance)
        distances = np.array(distances)
        nearest = np.partition(distances, self.k)[:self.k]
        mean = np.mean(nearest)
        return mean

    def ask(self):
        """returns a list of parameters"""
        # antithetic sampling
        if self.antithetic:
            self.epsilon_half = np.random.normal(
                scale=self.sigma, size=(self.half_popsize, self.num_params)
            )
            self.epsilon = np.concatenate([self.epsilon_half, -self.epsilon_half])
        else:
            self.epsilon = np.random.normal(
                scale=self.sigma, size=(self.popsize, self.num_params)
            )

        novelties = np.array(
            [
                self.calculate_novelty(self.characteristics[i,:])
                for i in self.characteristics_indices
            ]
        )
        probs = novelties / np.sum(novelties)
        self.current_index = np.random.choice([*range(self.metapopulation_size)], p=probs)
        self.current_solution = self.population[self.current_index]
        self.current_solutions = (
            self.current_solution.reshape(1, self.num_params) + self.epsilon
        )

        return self.current_solutions

    def tell(self, reward_table_result, novelties, evaluator):
        # input must be a numpy float array
        assert (
            len(reward_table_result) == self.popsize
        ), "Inconsistent reward_table size reported."

        gradient = self.get_gradient(
            compute_centered_ranks(novelties),
            compute_centered_ranks(reward_table_result),
        )
        new_sol = self.current_solution + self.optimizers[
            self.current_index
        ].compute_step(-gradient)

        fitness, characteristic = evaluator(new_sol)
        self.characteristics = np.append(
            self.characteristics, characteristic.reshape(1, characteristic.size), axis=0
        )
        new_sol_index = self.characteristics.shape[0] - 1
        self.population[self.current_index] = new_sol
        self.characteristics_indices[self.current_index] = new_sol_index
        self.update_bests(fitness, new_sol)

    def update_bests(self, fitness, new_sol):
        if fitness > self.best_reward:
            self.best_reward = fitness
            self.best = new_sol

    def current_param(self):
        return self.current_solution

    def set_mu(self, mu):
        self.mu = np.array(mu)

    def best_param(self):
        return self.best

    # return best params so far, along with historically best reward, curr reward, sigma
    def result(self):
        return (self.best, self.best_reward, self.best_reward, self.sigma)

    def init(self, evaluator):
        pop = np.random.randn(self.metapopulation_size, self.num_params)
        fitness, characteristics = evaluator(pop)
        self.characteristics = np.array(characteristics)
        self.population = pop
        best_fitness_index = np.argmax(fitness)
        self.best_reward = fitness[best_fitness_index]
        self.best = pop[best_fitness_index]
        self.characteristics_indices = [*range(self.metapopulation_size)]


class NSES(NSAbstract):
    """ NoveltySearch ES"""

    def __init__(
        self,
        num_params,  # number of model parameters
        optimizer,
        sigma=0.1,  # initial standard deviation
        popsize=256,  # population size
        metapopulation_size=10,
        k=10,
        antithetic=False,  # whether to use antithetic sampling
    ):
        super().__init__(
            num_params,
            optimizer,
            0,
            sigma,
            popsize,
            metapopulation_size,
            k,
            antithetic,
        )


class NSRES(NSAbstract):
    """ NoveltySearch ES"""

    def __init__(
        self,
        num_params,  # number of model parameters
        optimizer,
        weight=0.5,
        sigma=0.1,  # initial standard deviation
        metapopulation_size=10,
        popsize=256,  # population size
        k=10,
        antithetic=False,
    ):
        super().__init__(
            num_params,
            optimizer,
            weight,
            sigma,
            popsize,
            metapopulation_size,
            k,
            antithetic,
        )


class NSRAES(NSAbstract):
    """ NoveltySearch ES"""

    def __init__(
        self,
        num_params,  # number of model parameters
        optimizer,
        sigma=0.1,  # initial standard deviation
        popsize=256,  # population size
        metapopulation_size=10,
        k=5,
        init_weight=1,
        weight_change=0.05,
        weight_change_threshold=50,
        antithetic=False,
    ):
        super().__init__(
            num_params,
            optimizer,
            init_weight,
            sigma,
            popsize,
            metapopulation_size,
            k,
            antithetic,
        )
        self.weight_change = weight_change
        self.best_time = 0
        self.weight_change_threshold = weight_change_threshold

    def update_bests(self, fitness, new_sol):
        if fitness > self.best_reward:
            self.best_reward = fitness
            self.best = new_sol
            self.best_time = 0
            self.weight = min(1, self.weight + self.weight_change)
        else:
            self.best_time += 1
        if self.best_time >= self.weight_change_threshold:
            self.weight = min(0, self.weight - self.weight_change)
            self.best_time = 0
