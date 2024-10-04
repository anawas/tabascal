from datetime import datetime

import shutil
import os
import sys
import yaml
import subprocess

# os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"  # add this
# os.environ["XLA_PYTHON_CLIENT_ALLOCATOR"] = "platform"

import jax

# jax.config.update("jax_platform_name", "cpu")

import jax.profiler

import jax.numpy as jnp
from jax import random, vmap, jit
from jax.tree_util import tree_map

from jax.flatten_util import ravel_pytree as flatten

from numpyro.infer import MCMC, NUTS, Predictive

import matplotlib.pyplot as plt

from tabascal.jax.interferometry import ants_to_bl
from tabascal.utils.yaml import yaml_load, Tee
from tab_opt.data import extract_data
from tab_opt.opt import run_svi, svi_predict, f_model_flat, flatten_obs, post_samples
from tab_opt.gp import (
    get_times,
    kernel,
    resampling_kernel,
)
from tab_opt.plot import plot_predictions
from tab_opt.vis import averaging, get_rfi_phase
from tab_opt.models import (
    fixed_orbit_rfi_fft_standard,
    fixed_orbit_rfi_full_fft_standard_model,
)
from tab_opt.transform import affine_transform_full_inv, affine_transform_diag_inv

def tabascal_subtraction(conf_path: str, sim_dir: str):

    log = open('log_tab.txt', 'w')
    backup = sys.stdout
    sys.stdout = Tee(sys.stdout, log)

    print()
    start = datetime.now()
    print(f"Start Time : {start}")

    key, subkey = random.split(random.PRNGKey(1))


    # config["plots"]["init"] = 1
    # config["plots"]["truth"] = 1
    # config["plots"]["prior"] = 0
    # config["plots"]["prior_samples"] = 100
    # config["inference"]["mcmc"] = 0
    # config["inference"]["opt"] = 1
    # config["inference"]["fisher"] = 1
    # config["opt"]["guide"] = "map"
    # # epsilon = 3e-1
    # # epsilon = 3e-3
    # # config["opt"]["max_iter"] = 3_000
    # # config["opt"]["max_iter"] = 10

    # # config["fisher"]["n_samples"] = 10
    # # config["fisher"]["max_cg_iter"] = 10_000  # None

    # # config["fisher"]["n_samples"] = 1
    # # config["fisher"]["max_cg_iter"] = 1_000  # None

    # # 64 Antenna Case

    # # N_ant = 64
    # # N_time = 450
    # # config["data"]["sampling"] = 4
    # # N_sat = 1
    # # N_ast = 100
    # # config["init"]["truth"] = True


    # # 16 Antenna Case

    # config["init"]["truth"] = True

    # config["data"]["sampling"] = 1

    # # config["data"]["sampling"] = 4
    # # rfi_factor = 5e-3
    # epsilon = 1e-1
    # config["opt"]["max_iter"] = 100
    # # config["opt"]["max_iter"] = 1_000

    # config["fisher"]["n_samples"] = 1
    # config["fisher"]["max_cg_iter"] = 10_000  # None

    mem_i = 0

    ### Define Model
    vis_model = fixed_orbit_rfi_full_fft_standard_model


    def model(args, v_obs=None):
        return fixed_orbit_rfi_fft_standard(args, vis_model, v_obs)


    model_name = f"fixed_orbit_rfi"

    print(f"Model : {model_name}")


    results_name = f"fixed_orbit_rfi"


    config = yaml_load(conf_path)
    if config["data"]["sim_dir"] is None:
        config["data"]["sim_dir"] = os.path.abspath(sim_dir)
    else:
        sim_dir = os.path.abspath(config["data"]["sim_dir"])
        config["data"]["sim_dir"] = sim_dir

    config["model"] = {"name": model_name, "func": vis_model.__name__} 


    if sim_dir[-1]=="/":
        sim_dir = sim_dir[:-1]
    f_name = os.path.split(sim_dir)[1]

    print()
    print(f_name)
    print()

    zarr_path = os.path.join(sim_dir, f"{f_name}.zarr")
    ms_path = os.path.join(sim_dir, f"{f_name}.ms")

    plot_dir = os.path.join(sim_dir, "plots")
    results_dir = os.path.join(sim_dir, "results")
    mem_dir = os.path.join(sim_dir, "memory_profiles")

    os.makedirs(plot_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(mem_dir, exist_ok=True)

    map_path = os.path.join(results_dir, f"map_results_{results_name}.zarr")
    fisher_path = os.path.join(results_dir, f"fisher_results_{results_name}.zarr")

    # if not os.path.isdir(plot_dir):
    #     os.mkdir(plot_dir)

    # if not os.path.isdir(results_dir):
    #     os.mkdir(results_dir)

    # if not os.path.isdir(mem_dir):
    #     os.mkdir(mem_dir)

    (
        N_int_samples,
        N_ant,
        N_bl,
        a1,
        a2,
        times,
        times_fine,
        bl_uvw,
        ants_uvw,
        ants_xyz,
        vis_ast,
        vis_rfi,
        vis_obs,
        vis_cal,
        noise,
        noise_data,
        int_time,
        freqs,
        gains_ants,
        rfi_A_app,
        rfi_orbit,
    ) = extract_data(zarr_path, sampling=config["data"]["sampling"])

    N_rfi = len(rfi_orbit)
    N_time = len(times)

    ################
    del bl_uvw
    # del ants_uvw
    # del ants_xyz
    # del freqs
    # del rfi_orbit
    #################

    gains_true = vmap(jnp.interp, in_axes=(None, None, 1))(
        times, times_fine, gains_ants
    ).T
    vis_ast_true = vis_ast.reshape(N_time, N_int_samples, N_bl).mean(axis=1)
    vis_rfi_true = vis_rfi.reshape(N_time, N_int_samples, N_bl).mean(axis=1)
    # vis_obs = (
    #     (ants_to_bl(gains_ants, a1, a2) * (vis_ast + vis_rfi))
    #     .reshape(N_time, N_int_samples, N_bl, 1)
    #     .mean(axis=1)
    # ) + noise_data
    # vis_cal = (vis_obs / ants_to_bl(gains_true[:, :, None], a1, a2))
    # flag_rate = (
    #     100 * jnp.where(jnp.abs(vis_ast_true - vis_cal) > 3 * noise, True, False).mean()
    # )

    bl = jnp.arange(N_bl)

    print()
    print(f"Mean RFI Amp. : {jnp.mean(jnp.abs(vis_rfi_true)):.1f} Jy")
    print(f"Mean AST Amp. : {jnp.mean(jnp.abs(vis_ast_true)):.1f} Jy")
    # print(f"Flag Rate :     {flag_rate:.2f} %")
    print()
    print(f"Number of Antennas   : {N_ant: 4}")
    print(f"Number of Time Steps : {N_time: 4}")

    ### Vis AST Fourier modes
    ast_k = jnp.fft.fft(vis_ast_true, axis=0).T
    k_ast = jnp.fft.fftfreq(N_time, int_time)

    ast_k_mean = jnp.fft.fft(
        vis_ast_true.mean(axis=0)[None, :] * jnp.ones((N_time, 1)), axis=0
    ).T


    @jit
    def f(k, P0=1e3, k0=1e-3, gamma=1.0):
        k_ = (k / k0) ** 2
        return P0 * 0.5 * (jnp.exp(-0.5 * k_) + 1.0 / ((1.0 + k_) ** (gamma / 2)))


    ### GP Parameters

    g_amp_var = (1.0e-2) ** 2  # 1%
    g_phase_var = jnp.deg2rad(1.0) ** 2  # 1 degree
    g_amp_var = (1.0e-4) ** 2  # 1%
    g_phase_var = jnp.deg2rad(1.0e-2) ** 2  # 1 degree
    g_l = 3 * 60.0 * 60.0  # 3 hours

    rfi_var, rfi_l = 1e2, 15.0
    # rfi_var, rfi_l = jnp.sqrt(jnp.abs(vis_obs).max()), 15.0


    ### Gain Sampling Times
    g_times = get_times(times, g_l)
    gains_induce = vmap(jnp.interp, in_axes=(None, None, 1))(
        g_times, times_fine, gains_ants
    )
    n_g_times = len(g_times)

    ### RFI Sampling Times
    rfi_times = get_times(times, rfi_l)
    rfi_induce = jnp.array(
        [
            vmap(jnp.interp, in_axes=(None, None, 1))(
                rfi_times, times_fine, gains_ants * rfi_A_app[i]
            )
            for i in range(N_rfi)
        ]
    )
    n_rfi_times = len(rfi_times)

    print()
    print("Number of parameters per antenna/baseline")
    print(f"Gains : {n_g_times: 4}")
    print(f"RFI   : {n_rfi_times: 4}")
    print(f"AST   : {N_time: 4}")
    print()
    print(
        f"Number of parameters : {((2 * N_ant - 1) * n_g_times) + (2 * N_time * N_bl) + (2 * N_ant * n_rfi_times)}"
    )
    print(f"Number of data points: {2* N_bl * N_time}")


    ### Define RFI Kernel
    # @jit
    def rfi_kernel_fn(v_rfi, rfi_I, resample_rfi):
        return averaging((v_rfi / rfi_I)[:, None] * resample_rfi, N_int_samples)


    key, subkey = random.split(key)
    phase_error_std = 0e-2
    traj_phase_error = jnp.exp(
        1.0j
        * phase_error_std
        * random.normal(key, (N_rfi, N_ant, 1))
        * times_fine[None, None, :]
    )

    rfi_A_perturb = jnp.transpose(rfi_A_app, axes=(0, 2, 1)) * traj_phase_error

    resample_rfi = resampling_kernel(rfi_times, times_fine, rfi_var, rfi_l, 1e-8)

    rfi_phase = jnp.array(
        [
            get_rfi_phase(times_fine, orbit, ants_uvw, ants_xyz, freqs).T
            for orbit in rfi_orbit
        ]
    )

    ### Define True Parameters
    true_params = {
        **{f"g_amp_induce": jnp.abs(gains_induce)},
        **{f"g_phase_induce": jnp.angle(gains_induce[:-1])},
        **{f"rfi_r_induce": rfi_induce.real},
        **{f"rfi_i_induce": rfi_induce.imag},
        **{"ast_k_r": ast_k.real},
        **{"ast_k_i": ast_k.imag},
    }

    v_obs_ri = jnp.concatenate([vis_obs.real, vis_obs.imag], axis=0).T

    # Set Constant Parameters
    args = {
        "noise": noise if noise > 0 else 0.2,
        "vis_ast_true": vis_ast_true.T,
        "vis_rfi_true": vis_rfi_true.T,
        "gains_true": gains_true.T,
        "times": times,
        "times_fine": times_fine,
        "g_times": g_times,
        "N_time": N_time,
        "N_ants": N_ant,
        "N_bl": N_bl,
        "a1": a1,
        "a2": a2,
        "bl": bl,
        "n_int": int(N_int_samples),
    }

    pow_spec_args = config["pow_spec"]

    ### Define Prior Parameters
    args.update(
        {
            "mu_G_amp": jnp.abs(gains_induce),
            "mu_G_phase": jnp.angle(gains_induce[:-1]),
            # "mu_rfi_r": true_params["rfi_r_induce"],
            # "mu_rfi_i": true_params["rfi_i_induce"],
            "mu_rfi_r": jnp.zeros((N_rfi, N_ant, n_rfi_times)),
            "mu_rfi_i": jnp.zeros((N_rfi, N_ant, n_rfi_times)),
            # "mu_ast_k_r": true_params["ast_k_r"],
            # "mu_ast_k_i": true_params["ast_k_i"],
            "mu_ast_k_r": ast_k_mean.real,
            "mu_ast_k_i": ast_k_mean.imag,
            # "mu_ast_k_r": jnp.zeros((N_bl, N_time)),
            # "mu_ast_k_i": jnp.zeros((N_bl, N_time)),
            "L_G_amp": jnp.linalg.cholesky(kernel(g_times, g_times, g_amp_var, g_l, 1e-8)),
            "L_G_phase": jnp.linalg.cholesky(
                kernel(g_times, g_times, g_phase_var, g_l, 1e-8)
            ),
            "sigma_ast_k": jnp.array([f(k_ast, **pow_spec_args) for _ in range(N_bl)]),
            "L_RFI": jnp.linalg.cholesky(kernel(rfi_times, rfi_times, rfi_var, rfi_l)),
            "resample_g_amp": resampling_kernel(g_times, times, g_amp_var, g_l, 1e-8),
            "resample_g_phase": resampling_kernel(g_times, times, g_phase_var, g_l, 1e-8),
            "resample_rfi": resample_rfi,
            "rfi_phase": rfi_phase,
            # "rfi_kernel": rfi_kernel(vis_rfi, rfi_A_perturb, a1, a2),
        }
    )

    rfi_r_induce_init = (
        jnp.interp(rfi_times, times, jnp.sqrt(jnp.abs(vis_cal - vis_ast_true).max(axis=1)))[
            None, None, :
        ]
        * jnp.ones((N_rfi, N_ant, 1))
        / N_rfi
        + 1.0j * true_params["rfi_i_induce"]
    )

    # rfi_r_induce_init = args["mu_rfi_r"] + 1.0j * args["mu_rfi_i"]
    # rfi_r_induce_init = rfi_induce

    ast_k_init = jnp.fft.fft(
        vis_ast_true.mean(axis=0)[:, None] * jnp.ones((N_bl, N_time)), axis=1
    )

    n_sigma = 10.0
    ast_k_init = jnp.fft.fft(vis_ast_true + n_sigma * noise_data, axis=0).T

    # ast_k_init = ast_k

    init_params = {
        "g_amp_induce": true_params["g_amp_induce"],
        "g_phase_induce": true_params["g_phase_induce"],
        "ast_k_r": ast_k_init.real,
        "ast_k_i": ast_k_init.imag,
        "rfi_r_induce": rfi_r_induce_init.real,
        "rfi_i_induce": rfi_r_induce_init.imag,
    }

    if config["init"]["truth"]:
        init_params = true_params


    ################
    del gains_ants
    del rfi_A_app
    del ast_k
    del ast_k_mean
    del k_ast
    del gains_induce
    del rfi_induce
    del gains_true
    del vis_ast_true
    del vis_rfi_true
    del vis_cal
    del noise_data
    ################


    @jit
    def inv_transform(params, loc, inv_scaling):
        params_trans = {
            "rfi_r_induce_base": vmap(
                vmap(affine_transform_full_inv, (0, None, 0), 0), (1, None, 1), 1
            )(params["rfi_r_induce"], inv_scaling["L_RFI"], loc["mu_rfi_r"]),
            "rfi_i_induce_base": vmap(
                vmap(affine_transform_full_inv, (0, None, 0), 0), (1, None, 1), 1
            )(params["rfi_i_induce"], inv_scaling["L_RFI"], loc["mu_rfi_i"]),
            "g_amp_induce_base": vmap(affine_transform_full_inv, in_axes=(0, None, 0))(
                params["g_amp_induce"], inv_scaling["L_G_amp"], loc["mu_G_amp"]
            ),
            "g_phase_induce_base": vmap(affine_transform_full_inv, in_axes=(0, None, 0))(
                params["g_phase_induce"], inv_scaling["L_G_phase"], loc["mu_G_phase"]
            ),
            "ast_k_r_base": vmap(affine_transform_diag_inv, in_axes=(0, 0, 0))(
                params["ast_k_r"], inv_scaling["sigma_ast_k"], loc["mu_ast_k_r"]
            ),
            "ast_k_i_base": vmap(affine_transform_diag_inv, in_axes=(0, 0, 0))(
                params["ast_k_i"], inv_scaling["sigma_ast_k"], loc["mu_ast_k_i"]
            ),
        }
        return params_trans


    inv_scaling = {
        "L_RFI": jnp.linalg.inv(args["L_RFI"]),
        "L_G_amp": jnp.linalg.inv(args["L_G_amp"]),
        "L_G_phase": jnp.linalg.inv(args["L_G_phase"]),
        "sigma_ast_k": 1.0 / args["sigma_ast_k"],
    }

    true_params_base = inv_transform(true_params, args, inv_scaling)

    init_params_base = inv_transform(init_params, args, inv_scaling)

    print()
    end_start = datetime.now()
    print(f"End Time   : {end_start}")
    print(f"Total Time : {end_start - start}")

    mem_i += 1
    jax.profiler.save_device_memory_profile(
        os.path.join(mem_dir, f"memory_{mem_i}.prof")
    )

    guides = {
        "map": "AutoDelta",
    }


    def reduced_chi2(pred, true, noise):
        rchi2 = ((jnp.abs(pred - true) / noise) ** 2).sum() / (2 * true.size)
        return rchi2

    def write_xds(vi_pred, file_path, overwrite=True):
        import dask.array as da
        import xarray as xr

        map_xds = xr.Dataset(
            data_vars={
                "ast_vis": (["sample", "bl", "time"], da.asarray(vi_pred["ast_vis"])),
                "gains": (["sample", "ant", "time"], da.asarray(vi_pred["gains"])),
                "rfi_vis": (["sample", "bl", "time"], da.asarray(vi_pred["rfi_vis"])),
                "vis_obs": (["sample", "bl", "time"], da.asarray(vi_pred["vis_obs"])),
                },
            coords={"time": da.asarray(times)},
            )
        
        mode = "w" if overwrite else "w-"

        map_xds.to_zarr(file_path, mode=mode)
        
        return map_xds


    ### Check and Plot Model at init params
    pred = Predictive(
        model=model,
        posterior_samples=tree_map(lambda x: x[None, :], init_params_base),
        batch_ndims=1,
    )
    key, subkey = random.split(key)
    init_pred = pred(subkey, args=args)
    rchi2 = reduced_chi2(init_pred["vis_obs"][0], vis_obs.T, noise)
    print()
    print(f"Reduced Chi^2 @ init: {rchi2}")
    print()

    ### Check and Plot Model at true parameters
    pred = Predictive(
        model=model,
        posterior_samples=tree_map(lambda x: x[None, :], true_params_base),
        batch_ndims=1,
    )
    key, subkey = random.split(key)
    true_pred = pred(subkey, args=args)
    rchi2 = reduced_chi2(true_pred["vis_obs"][0], vis_obs.T, noise)
    print()
    print(f"Reduced Chi^2 @ true: {rchi2}")
    print()


    if config["plots"]["init"]:
        plot_predictions(
            times=times,
            pred=init_pred,
            args=args,
            type="init",
            model_name=model_name,
            max_plots=10,
            save_dir=plot_dir,
        )

    if config["plots"]["truth"]:
        plot_predictions(
            times=times,
            pred=true_pred,
            args=args,
            type="true",
            model_name=model_name,
            max_plots=10,
            save_dir=plot_dir,
        )

    print()
    end_true = datetime.now()
    print(f"End Time  : {end_true}")
    print(f"Init/True Plot Time : {end_true - end_start}")

    mem_i += 1
    jax.profiler.save_device_memory_profile(
        os.path.join(mem_dir, f"memory_{mem_i}.prof")
    )

    ### Check and Plot Model at prior parameters
    key, subkey = random.split(key)
    if config["plots"]["prior"]:
        pred = Predictive(model, num_samples=config["plots"]["prior_samples"])
        prior_pred = pred(subkey, args=args)
        print("Prior Samples Drawn")
        plot_predictions(
            times=times,
            pred=prior_pred,
            args=args,
            type="prior",
            model_name=model_name,
            max_plots=10,
            save_dir=plot_dir,
        )


    print()
    end_prior = datetime.now()
    print(f"End Time  : {end_prior}")
    print(f"Prior Plot Time : {end_prior - end_true}")

    ### Run Inference
    key, *subkeys = random.split(key, 3)
    if config["inference"]["mcmc"]:
        num_warmup = 500
        num_samples = 1000

        nuts_kernel = NUTS(model, dense_mass=False)  # [('g_phase_0', 'g_phase_1')])
        mcmc = MCMC(nuts_kernel, num_warmup=num_warmup, num_samples=num_samples)
        mcmc.run(
            subkeys[0],
            args=args,
            v_obs=v_obs_ri,
            extra_fields=("potential_energy",),
            init_params=true_params_base,
        )

        pred = Predictive(model, posterior_samples=mcmc.get_samples())
        mcmc_pred = pred(subkeys[1], args=args)
        plot_predictions(
            times=times,
            pred=mcmc_pred,
            args=args,
            type="mcmc",
            model_name=model_name,
            max_plots=10,
            save_dir=plot_dir,
        )

    print()
    end_mcmc = datetime.now()
    print(f"End Time  : {end_mcmc}")
    print(f"MCMC Plot Time : {end_mcmc - end_prior}")

    mem_i += 1
    jax.profiler.save_device_memory_profile(
        os.path.join(mem_dir, f"memory_{mem_i}.prof")
    )

    key, *subkeys = random.split(key, 3)
    if config["inference"]["opt"]:
        guide_family = guides[config["opt"]["guide"]]
        vi_results, vi_guide = run_svi(
            model=model,
            args=args,
            obs=v_obs_ri,
            max_iter=config["opt"]["max_iter"],
            guide_family=guide_family,
            init_params={
                **{k + "_auto_loc": v for k, v in init_params_base.items()},
            },
            epsilon=config["opt"]["epsilon"],
            key=subkeys[0],
        )
        vi_params = vi_results.params
        vi_pred = svi_predict(
            model=model,
            guide=vi_guide,
            vi_params=vi_params,
            args=args,
            num_samples=1,
            key=subkeys[1],
        )

        map_xds = write_xds(vi_pred, map_path)

        plot_predictions(
            times,
            pred=vi_pred,
            args=args,
            type=config["opt"]["guide"],
            model_name=model_name,
            max_plots=10,
            save_dir=plot_dir,
        )

        rchi2 = reduced_chi2(vi_pred["vis_obs"][0], vis_obs.T, noise)
        print()
        print(f"Reduced Chi^2 @ opt: {rchi2}")
        print()

        plt.semilogy(vi_results.losses)
        plt.savefig(os.path.join(plot_dir, f"{model_name}_opt_loss.pdf"), format="pdf")
        
        del vi_pred
        del vi_results


    print()
    end_opt = datetime.now()
    print(f"End Time  : {end_opt}")
    print(f"Opt Plot Time : {end_opt - end_prior}")

    mem_i += 1
    jax.profiler.save_device_memory_profile(
        os.path.join(mem_dir, f"memory_{mem_i}.prof")
    )

    key, *subkeys = random.split(key, 3)
    if config["inference"]["fisher"] and rchi2 < 1.1:

        print("Calculating Fisher Samples ...")

        f_model = lambda params, args: vis_model(params, args)[0]
        model_flat = lambda params: f_model_flat(f_model, params, args)

        post_mean = {k[:-9]: v for k, v in vi_params.items()} if config["inference"]["opt"] else true_params_base

        dtheta = post_samples(
            model_flat,
            post_mean,
            flatten_obs(vis_obs),
            noise,
            config["fisher"]["n_samples"],
            subkeys[0],
            config["fisher"]["max_cg_iter"],
        )

        samples = tree_map(jnp.add, post_mean, dtheta)

        pred = Predictive(model, posterior_samples=samples)
        fisher_pred = pred(subkeys[1], args=args)

        fisher_xds = write_xds(fisher_pred, fisher_path)

        plot_predictions(
            times=times,
            pred=fisher_pred,
            args=args,
            type="fisher_opt" if config["inference"]["opt"] else "fisher_true",
            model_name=model_name,
            max_plots=10,
            save_dir=plot_dir,
        )

    print()
    end_fisher = datetime.now()
    print(f"End Time  : {end_fisher}")
    print(f"Fisher Plot Time : {end_fisher - end_opt}")

    print()
    end_final = datetime.now()
    print(f"End Time  : {end_final}")
    print(f"Total Time : {end_final - start}")

    mem_i += 1
    jax.profiler.save_device_memory_profile(
        os.path.join(mem_dir, f"memory_{mem_i}.prof")
    )

    print()
    print("Copying tabascal results to MS file in TAB_DATA column")
    subprocess.run(f"tab2MS -m {ms_path} -z {map_path}", shell=True, executable="/bin/bash")    

    log.close()
    shutil.copy("log_tab.txt", sim_dir)
    os.remove("log_tab.txt")
    sys.stdout = backup

    with open(os.path.join(sim_dir, "tab_config.yaml"), "w") as fp:
        yaml.dump(config, fp)

    
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Apply tabascal to a simulation."
    )
    parser.add_argument(
        "-s", "--sim_dir", help="Path to the directory of the simulation."
    )
    parser.add_argument(
        "-c", "--config", required=True, help="Path to the config file."
    )
    args = parser.parse_args()
    sim_dir = args.sim_dir
    conf_path = args.config   

    tabascal_subtraction(conf_path, sim_dir) 

if __name__=="__main__":
    main()