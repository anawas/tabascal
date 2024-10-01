from bdsf import process_image
import pandas as pd
import numpy as np

from astropy.coordinates import SkyCoord
from astropy.io import fits
import argparse
import os

from tabascal.jax.coordinates import radec_to_lmn
from tabascal.jax.interferometry import airy_beam

import xarray as xr

def construct_src_df(xds: xr.Dataset) -> pd.DataFrame:

    def construct_src_subdf(radec, I):
        df = pd.DataFrame(
                data=np.concatenate(
                    [
                        radec,
                        I,
                        np.zeros((len(I), 1))
                    ],
                    axis=1
                ),
                columns=[" RA", " DEC", " Total_flux", " E_Total_flux"],
            )
        return df

    no_sources = construct_src_subdf(np.zeros((0, 2)), np.zeros((0, 1)))

    if xds.n_ast_p_src > 0:
        p_df = construct_src_subdf(xds.ast_p_radec.data, xds.ast_p_I.data[:, 0, :])
    else:
        p_df = no_sources

    if xds.n_ast_g_src > 0:
        g_df = construct_src_subdf(xds.ast_g_radec.data, xds.ast_g_I.data[:, 0, :])
    else:
        g_df = no_sources

    if xds.n_ast_e_src > 0:
        e_df = construct_src_subdf(xds.ast_e_radec.data, xds.ast_e_I.data[:, 0, :])
    else:
        e_df = no_sources

    source_df = pd.concat([p_df, g_df, e_df])

    return source_df

def extract(img_path: str, zarr_path: str, n_sigma: float=3.0, beam_corr: bool=True) -> None:

    # tclean naming convention
    # img_name = os.path.splitext(img_path)[0]
    # wsclean naming convention
    img_name = img_path.removesuffix("-image.fits")

    bmaj = fits.getheader(img_path)["BMAJ"]*3600

    print(f"Beam Major : {bmaj:.2f} arcsec")

    # image = process_image(
    #     img_path, quiet=True, thresh_isl=2.0, thresh_pix=1.0
    # )
    image = process_image(img_path, thresh_isl=1.0, thresh_pix=1.0, quiet=True)

    image.export_image(outfile=img_name + ".gauss_resid.fits", img_type="gaus_resid", clobber=True)
    image.write_catalog(
        outfile=img_name + ".pybdsf.csv", format="csv", catalog_type="srl", clobber=True
    )

    # tclean naming convention
    # resid_ext = ".resid.fits"
    # wsclean naming convention
    resid_ext = "-residual.fits"

    with fits.open(img_name + resid_ext) as hdul:
        noise = np.nanstd(hdul[0].data[0, 0])  # *image.pixel_beamarea()

    xds = xr.open_zarr(zarr_path)
    keys2 = [" RA", " DEC", " Total_flux", " E_Total_flux"]
    true_df = construct_src_df(xds).sort_values(" Total_flux").reset_index()[keys2]
    true_df.to_csv("true_sources.csv")

    df = pd.read_csv(img_name + ".pybdsf.csv", skiprows=5)
    keys1 = [
        " Isl_id",
        " RA",
        " E_RA",
        " DEC",
        " E_DEC",
        " Total_flux",
        " E_Total_flux",
        " Maj",
        " E_Maj",
        " Min",
        " E_Min",
        " PA",
        " E_PA",
    ]
    image_df = (
        df[df[" Total_flux"] > n_sigma*noise][keys1]
        .sort_values(" Total_flux")
        .reset_index()[keys1]
    )

    c = SkyCoord(ra=image_df[" RA"], dec=image_df[" DEC"], unit="deg")
    catalog = SkyCoord(ra=true_df[" RA"], dec=true_df[" DEC"], unit="deg")
    idx, d2d, d3d = c.match_to_catalog_sky(catalog)

    true_df1 = true_df.iloc[idx].reset_index()[keys2]
    image_df1 = image_df[keys2]

    if beam_corr:

        lmn = radec_to_lmn(image_df1[" RA"].values, image_df1[" DEC"].values, [xds.target_ra, xds.target_dec])
        theta = np.arcsin(np.linalg.norm(lmn[:, :-1], axis=-1))
        beam = airy_beam(theta[:,None,None], xds.freq.data, xds.dish_diameter)[:,0,0,0]**2
        image_df1.loc[:," Total_flux"] = beam * image_df1[" Total_flux"]
        image_df1.loc[:," E_Total_flux"] = beam * image_df1[" E_Total_flux"]

    error_df = np.abs((image_df1 - true_df1))
    error_df = pd.DataFrame(
        data=np.abs((image_df1 - true_df1)[[" RA", " DEC"]] * 3600).values,
        columns=["E_RA [as]", "E_DEC [as]"],
    )
    error_df["E_Total_flux [%]"] = (
        100 * (image_df1 - true_df1)[" Total_flux"] / true_df1[" Total_flux"]
    )
    error_df[["RA [deg]", "DEC [deg]"]] = true_df1[[" RA", " DEC"]]
    error_df["Total_flux_true [mJy]"] = 1e3 * true_df1[" Total_flux"]
    error_df["Total_flux_image [mJy]"] = 1e3 * image_df1[" Total_flux"]
    error_df["SNR"] = image_df1[" Total_flux"] / noise
    error_df["Total_flux_std [mJy]"] = 1e3 * image_df1[" E_Total_flux"]
    error_df["Image_noise [mJy/beam]"] = (
        1e3 * image_df1[" Total_flux"] / image_df1[" Total_flux"] * noise
    )
    error_df["E_RADEC [as]"] = d2d.arcsec

    mask = d2d.arcsec < bmaj

    keys = [
        "RA [deg]",
        "E_RA [as]",
        "DEC [deg]",
        "E_DEC [as]",
        "Total_flux_true [mJy]",
        "E_Total_flux [%]",
        "E_RADEC [as]",
        "Total_flux_image [mJy]",
        "Total_flux_std [mJy]",
        "SNR",
        "Image_noise [mJy/beam]",
    ]
    error_df = error_df[keys].iloc[mask]

    error_df.to_csv(img_name + ".csv", index=False)


def main():
    program_desc = "Extract and measure sources from FITS file using PyBDSF."
    parser = argparse.ArgumentParser(description=program_desc)
    # Output File Arguments
    parser.add_argument("--zarr_path", help="Path to zarr simulation file.")
    parser.add_argument("--img_path", help="Path to image or directory of images if '--type' is specified.")
    parser.add_argument(
        "--type",
        default=None,
        help="Data type to image. {'AST', 'CAL', 'TAB'}",
    )
    args = parser.parse_args()

    zarr_path = args.zarr_path
    img_path = args.img_path
    if args.type is not None:
        data_types = args.type.upper().split(",")
        img_paths = [os.path.join(img_path, f"{d_type}_DATA-image.fits") for d_type in data_types]
    else:
        img_paths = [img_path]

    for img_path in img_paths:
        extract(img_path, zarr_path)