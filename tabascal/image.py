from casatasks import tclean, exportfits
import shutil
import os


def image_ms(ms_path, image_path, overwrite=False):
    if os.path.exists(image_path):
        if overwrite:
            shutil.rmtree(image_path)
            os.makedirs(image_path)
        else:
            raise FileExistsError(f"File {image_path} already exists.")
    else:
        os.makedirs(image_path)

    tclean(
        vis=ms_path,
        selectdata=True,
        field="",
        spw="",
        timerange="",
        uvrange="",
        antenna="",
        scan="",
        observation="",
        intent="",
        datacolumn="corrected",
        imagename=image_path,
        imsize=1024,
        cell="4arcsec",
        phasecenter="",
        stokes="I",
        projection="SIN",
        startmodel="",
        specmode="mfs",
        reffreq="",
        nchan=-1,
        start="",
        width="",
        outframe="LSRK",
        veltype="radio",
        restfreq=[],
        interpolation="linear",
        perchanweightdensity=True,
        gridder="standard",
        facets=1,
        psfphasecenter="",
        wprojplanes=1,
        vptable="",
        mosweight=True,
        aterm=True,
        psterm=False,
        wbawp=True,
        conjbeams=False,
        cfcache="",
        usepointing=False,
        computepastep=360.0,
        rotatepastep=360.0,
        pointingoffsetsigdev=[],
        pblimit=0.01,
        normtype="flatnoise",
        deconvolver="hogbom",
        scales=[],
        nterms=2,
        smallscalebias=0.0,
        restoration=True,
        restoringbeam=[],
        pbcor=True,
        outlierfile="",
        weighting="briggs",
        robust=-0.5,
        noise="0uJy",  #    noise='360uJy',
        npixels=0,
        uvtaper=[],
        niter=100000,  # niter=10000,
        gain=0.1,
        threshold=3 * 6.8e-4,  # threshold=0.0,
        nsigma=0.0,
        cycleniter=-1,
        cyclefactor=1.0,
        minpsffraction=0.05,
        maxpsffraction=0.8,
        interactive=False,
        usemask="user",
        mask="",
        pbmask=0.0,
        sidelobethreshold=3.0,
        noisethreshold=2.0,
        lownoisethreshold=1.5,
        negativethreshold=0.0,
        smoothfactor=1.0,
        minbeamfrac=0.3,
        cutthreshold=0.01,
        growiterations=75,
        dogrowprune=True,
        minpercentchange=-1.0,
        verbose=False,
        fastnoise=True,
        restart=True,
        savemodel="none",
        calcres=True,
        calcpsf=True,
        psfcutoff=0.35,
        parallel=False,
    )

    exportfits(
        imagename=image_path + ".image",
        fitsimage=image_path + ".fits",
        velocity=False,
        optical=False,
        bitpix=-32,
        minpix=0,
        maxpix=-1,
        overwrite=True,
        dropstokes=False,
        stokeslast=True,
        history=True,
        dropdeg=False,
    )

    exportfits(
        imagename=image_path + ".residual",
        fitsimage=image_path + ".resid.fits",
        velocity=False,
        optical=False,
        bitpix=-32,
        minpix=0,
        maxpix=-1,
        overwrite=True,
        dropstokes=False,
        stokeslast=True,
        history=True,
        dropdeg=False,
    )