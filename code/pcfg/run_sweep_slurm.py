import subprocess


def main():
    num_iterations = 2000
    logging_interval = 10
    eval_interval = 10
    checkpoint_interval = 100
    batch_size = 10
    pcfg_path = './pcfgs/astronomers_pcfg.json'
    exp_levenshtein = True
    for seed in [1, 2, 3]:
        for train_mode in ['ws', 'vimco', 'ww', 'reinforce']:
            for num_particles in [5, 10, 20, 50, 100]:
                subprocess.call(
                    'sbatch run_slurm.sh {} {} {} {} {} {} {} {} {} {}'.format(
                        train_mode, num_iterations, logging_interval,
                        eval_interval, checkpoint_interval, batch_size,
                        num_particles, seed, pcfg_path, exp_levenshtein),
                    shell=True)


if __name__ == '__main__':
    main()
