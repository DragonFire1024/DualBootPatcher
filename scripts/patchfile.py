#!/usr/bin/env python3

# For Qualcomm based Samsung Galaxy S4 only!

import gzip
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ramdisk_offset  = "0x02000000"
rootdir         = os.path.dirname(os.path.realpath(__file__))
rootdir         = os.path.join(rootdir, "..")
ramdiskdir      = os.path.join(rootdir, "ramdisks")
patchdir        = os.path.join(rootdir, "patches")
binariesdir     = os.path.join(rootdir, "binaries")
remove_dirs     = []

mkbootimg       = "mkbootimg"
unpackbootimg   = "unpackbootimg"
if os.name == "nt":
  mkbootimg     = "mkbootimg.exe"
  unpackbootimg = "unpackbootimg.exe"

class FileInfo:
  def __init__(self):
    self.patch = ""
    self.ramdisk = ""
    self.bootimg = "boot.img"
    self.has_boot_image = True

def clean_up_and_exit(exit_status):
  for d in remove_dirs:
    shutil.rmtree(d)
  sys.exit(exit_status)

def read_file_one_line(filepath):
  f = open(filepath, 'r')
  line = f.readline()
  f.close()
  return line.strip('\n')

def run_command(command):
  try:
    process = subprocess.Popen(
      command,
      stdout = subprocess.PIPE,
      universal_newlines = True
    )
    output = process.communicate()[0]
    exit_status = process.returncode
    return (exit_status, output)
  except:
    print("Failed to run command: \"%s\"" % ' '.join(command))
    clean_up_and_exit(1)

def apply_patch_file(patchfile, directory):
  patch = "patch"
  if os.name == "nt":
    # Windows wants anything named patch.exe to run as Administrator
    patch = os.path.join(binariesdir, "hctap.exe")

  exit_status, output = run_command(
    [ patch,
      '-p', '1',
      '-d', directory,
      '-i', os.path.join(patchdir, patchfile)]
  )
  if exit_status != 0:
    print("Failed to apply patch")
    clean_up_and_exit(1)

def patch_boot_image(boot_image, file_info):
  tempdir = tempfile.mkdtemp()
  remove_dirs.append(tempdir)

  exit_status, output = run_command(
    [ os.path.join(binariesdir, unpackbootimg),
      '-i', boot_image,
      '-o', tempdir]
  )
  if exit_status != 0:
    print("Failed to extract boot image")
    clean_up_and_exit(1)

  prefix   = os.path.join(tempdir, os.path.split(boot_image)[1])
  base     = "0x" + read_file_one_line(prefix + "-base")
  cmdline  =        read_file_one_line(prefix + "-cmdline")
  pagesize =        read_file_one_line(prefix + "-pagesize")
  os.remove(prefix + "-base")
  os.remove(prefix + "-cmdline")
  os.remove(prefix + "-pagesize")
  os.remove(prefix + "-ramdisk.gz")
  shutil.move(prefix + "-zImage", os.path.join(tempdir, "kernel.img"))

  if not file_info.ramdisk:
    print("No ramdisk specified")
    return None

  # Extract ramdisk from tar.xz
  if sys.hexversion >= 50528256: # Python 3.3
    with tarfile.open(os.path.join(ramdiskdir, "ramdisks.tar.xz")) as f:
      f.extract(file_info.ramdisk, path = ramdiskdir)
  else:
    xz = "xz"
    if os.name == "nt":
      xz = os.path.join(binariesdir, "xz.exe")

    run_command(
      [ xz, '-d', '-k', '-f', os.path.join(ramdiskdir, "ramdisks.tar.xz") ]
    )

    with tarfile.open(os.path.join(ramdiskdir, "ramdisks.tar")) as f:
      f.extract(file_info.ramdisk, path = ramdiskdir)

    os.remove(os.path.join(ramdiskdir, "ramdisks.tar"))

  ramdisk = os.path.join(ramdiskdir, file_info.ramdisk)

  # Compress ramdisk with gzip if it isn't already
  if not file_info.ramdisk.endswith(".gz"):
    with open(ramdisk, 'rb') as f_in:
      with gzip.open(ramdisk + ".gz", 'wb') as f_out:
        f_out.writelines(f_in)

    os.remove(os.path.join(ramdiskdir, file_info.ramdisk))
    ramdisk = ramdisk + ".gz"

  shutil.copyfile(ramdisk, os.path.join(tempdir, "ramdisk.cpio.gz"))

  os.remove(os.path.join(ramdiskdir, file_info.ramdisk + ".gz"))

  exit_status, output = run_command(
    [ os.path.join(binariesdir, mkbootimg),
      '--kernel',         os.path.join(tempdir, "kernel.img"),
      '--ramdisk',        os.path.join(tempdir, "ramdisk.cpio.gz"),
      '--cmdline',        cmdline,
      '--base',           base,
      '--pagesize',       pagesize,
      '--ramdisk_offset', ramdisk_offset,
      '--output',         os.path.join(tempdir, "complete.img")]
  )

  os.remove(os.path.join(tempdir, "kernel.img"))
  os.remove(os.path.join(tempdir, "ramdisk.cpio.gz"))

  if exit_status != 0:
    print("Failed to create boot image")
    clean_up_and_exit(1)

  return os.path.join(tempdir, "complete.img")

def patch_zip(zip_file, file_info):
  print("--- Please wait. This may take a while ---")

  tempdir = tempfile.mkdtemp()
  remove_dirs.append(tempdir)

  z = zipfile.ZipFile(zip_file, "r")
  z.extractall(tempdir)
  z.close()

  if file_info.has_boot_image:
    boot_image = os.path.join(tempdir, file_info.bootimg)
    new_boot_image = patch_boot_image(boot_image, file_info)

    os.remove(boot_image)
    shutil.move(new_boot_image, boot_image)
  else:
    print("No boot image to patch")

  shutil.copy(os.path.join(patchdir, "dualboot.sh"), tempdir)

  if file_info.patch != "":
    apply_patch_file(file_info.patch, tempdir)

  new_zip_file = os.path.join(tempdir, "complete.zip")
  z = zipfile.ZipFile(new_zip_file, 'w', zipfile.ZIP_DEFLATED)
  for root, dirs, files in os.walk(tempdir):
    for f in files:
      if f == "complete.zip":
        continue
      arcdir = os.path.relpath(root, start = tempdir)
      z.write(os.path.join(root, f), arcname = os.path.join(arcdir, f))
  z.close()

  return new_zip_file

def get_file_info(path):
  filename = os.path.split(path)[1]
  file_info = FileInfo()

  # Custom kernels
  if re.search(r"^.*\.img$", filename):
    print("Detected boot.img file")
    print("WILL USE CYANOGENMOD RAMDISK. USE replaceramdisk SCRIPT TO CHOOSE ANOTHER RAMDISK")
    file_info.ramdisk = "cyanogenmod.dualboot.cpio"

  elif re.search(r"^KT-SGS4-JB4.3-AOSP-.*.zip$", filename):
    print("Detected ktoonsez kernel zip")
    print("Using patched ktoonsez ramdisk")
    file_info.ramdisk = "ktoonsez.dualboot.cpio"
    file_info.patch   = "ktoonsez.dualboot.patch"

  elif re.search(r"^jflte[a-z]+-aosp-faux123-.*.zip$", filename):
    print("Detected faux kernel zip")
    print("Using patched Cyanogenmod ramdisk (compatible with faux)")
    file_info.ramdisk = "cyanogenmod.dualboot.cpio"
    file_info.patch   = "faux.dualboot.patch"

  elif re.search(r"^ChronicKernel-JB4.3-AOSP-.*.zip$", filename):
    print("Detected ChronicKernel kernel zip")
    print("Using patched ChronicKernel ramdisk")
    file_info.ramdisk = "chronickernel.dualboot.cpio"
    file_info.patch   = "chronickernel.dualboot.patch"

  elif re.search(r"^Infamous_S4_Kernel.v.*.zip$", filename):
    print("Detected Infamous kernel zip")
    print("Using patched Infamous kernel ramdisk")
    file_info.ramdisk = "infamouskernel.dualboot.cpio"
    file_info.patch   = "infamouskernel.dualboot.patch"

  elif re.search(r"^v[0-9]+-Google-edition-ausdim-Kernel-.*.zip$", filename):
    print("Detected Ausdim kernel zip")
    print("Using patched Ausdim kernel ramdisk")
    print("NOTE: The ramdisk is based on Ausdim v17. If a newer version has ramdisk changes, let me know")
    file_info.ramdisk = "ausdim.dualboot.cpio"
    file_info.patch   = "ausdim.dualboot.patch"

  elif re.search(r"^.*_AdamKernel.V[0-9\.]+\.CWM\.zip$", filename):
    print("Detected Adam kernel zip")
    print("Using patched Adam kernel zip")
    file_info.ramdisk = "adam.dualboot.cpio"
    file_info.patch   = "adam.dualboot.patch"
    file_info.bootimg = "wanam/boot.img"

  # Cyanogenmod ROMs
  elif re.search(r"^cm-[0-9\.]+-[0-9]+-NIGHTLY-[a-z0-9]+.zip$", filename):
    print("Detected official Cyanogenmod nightly ROM zip")
    print("Using patched Cyanogenmod ramdisk")
    file_info.ramdisk = "cyanogenmod.dualboot.cpio"
    file_info.patch   = "cyanogenmod.dualboot.patch"

  elif re.search(r"^cm-[0-9\.]+-[0-9]+-.*.zip$", filename):
    # My ROM has built in dual-boot support
    if "noobdev" in filename:
      print("ROM has built in dual boot support")
      clean_up_and_exit(1)

    print("Detected Cyanogenmod based ROM zip")
    print("Using patched Cyanogenmod ramdisk")
    file_info.ramdisk = "cyanogenmod.dualboot.cpio"
    file_info.patch   = "cyanogenmod.dualboot.patch"

  elif re.search(r"^Slim-.*.zip$", filename):
    print("Detected Slim Bean ROM zip")
    print("Using patched Cyanogenmod ramdisk (compatible with Slim Bean)")
    file_info.ramdisk = "cyanogenmod.dualboot.cpio"
    file_info.patch   = "slim.dualboot.patch"

  # AOKP ROMs
  elif re.search(r"^aokp_[0-9\.]+_[a-z0-9]+_task650_[0-9\.]+.zip$", filename):
    print("Detected Task650's AOKP ROM zip")
    print("Using patched Task650's AOKP ramdisk")
    file_info.ramdisk = "aokp-task650.dualboot.cpio"
    file_info.patch   = "aokp-task650.dualboot.patch"

  # PAC-Man ROMs
  elif re.search(r"^pac_[a-z0-9]+_.*.zip$", filename):
    print("Detected PAC-Man ROM zip")
    print("Using patched Cyanogenmod ramdisk (compatible with PAC-Man)")
    file_info.ramdisk = "cyanogenmod.dualboot.cpio"
    file_info.patch   = "cyanogenmod.dualboot.patch"

  elif re.search(r"^pac_[a-z0-9]+-nightly-[0-9]+.zip$", filename):
    print("Detected PAC-Man nightly ROM zip")
    print("Using patched Cyanogenmod ramdisk (compatible with PAC-Man)")
    file_info.ramdisk = "cyanogenmod.dualboot.cpio"
    file_info.patch   = "cyanogenmod.dualboot.patch"

  # ParanoidAndroid ROMs
  elif re.search(r"^pa_[a-z0-9]+-.*-[0-9]+.zip$", filename):
    print("Detected ParanoidAndroid ROM zip")
    print("Using patched ParanoidAndroid ramdisk")
    file_info.ramdisk = "paranoidandroid.dualboot.cpio"
    file_info.patch   = "paranoidandroid.dualboot.patch"

  # Carbon ROMs
  elif re.search(r"CARBON-JB-.*-[a-z0-9]+\.zip", filename):
    if 'NIGHTLY' in filename:
      print("Detected Carbon Nightly ROM zip")
    else:
      print("Detected Carbon ROM zip")
    print("Using patched Carbon ramdisk")
    file_info.ramdisk = "carbon.dualboot.cpio"
    file_info.patch   = "carbon.dualboot.patch"

  # Google Edition ROMs
  elif re.search(r"^i9505-ge-untouched-4.3-.*.zip$", filename):
    print("Detected MaKTaiL's Google Edition ROM zip")
    print("Using patched Google Edition ramdisk")
    file_info.ramdisk = "googleedition.dualboot.cpio"
    file_info.patch   = "ge-MaKTaiL.dualboot.patch"

  # MIUI ROMs
  elif re.search(r"^miuiandroid_.*.zip$", filename):
    if "gapps" in filename:
      print("Detected MIUI Google Apps zip")
      file_info.patch = "gapps-miui.dualboot.patch"
      file_info.has_boot_image = False
    else:
      print("Detected MIUI ROM zip")
      print("Using patched MIUI ramdisk")
      file_info.ramdisk = "miui.dualboot.cpio"
      file_info.patch   = "miui.dualboot.patch"

  # TouchWiz ROMs
  elif re.search(r"^FoxHound_.*\.zip$", filename):
    print("Detected FoxHound ROM zip")
    print("Using patched TouchWiz kernel zip")
    file_info.ramdisk = "touchwiz.dualboot.cpio"
    file_info.patch   = "foxhound.dualboot.patch"
    file_info.bootimg = "snakes/Kernels/Stock/boot.img"

  # Google Apps
  elif re.search(r"^gapps-jb-[0-9]{8}-signed.zip$", filename):
    print("Detected Cyanogenmod Google Apps zip")
    file_info.patch = "cyanogenmod-gapps.dualboot.patch"
    file_info.has_boot_image = False

  elif re.search(r"^gapps-jb\([0-9\.]+\)-[0-9\.]+.zip$", filename):
    print("Detected Task650's Google Apps zip")
    file_info.patch = "gapps-task650.dualboot.patch"
    file_info.has_boot_image = False

  elif re.search(r"^Slim_AIO_gapps.*.zip$", filename):
    print("Detected Slim Bean Google Apps zip")
    file_info.patch = "gapps-slim.dualboot.patch"
    file_info.has_boot_image = False

  # SuperSU
  elif re.search(r"^UPDATE-SuperSU-v[0-9\.]+.zip$", filename):
    print("Detected Chainfire's SuperSU zip")
    file_info.patch = "supersu.dualboot.patch"
    file_info.has_boot_image = False

  else:
    return None

  return file_info

def detect_file_type(path):
  if path.endswith(".zip"):
    return "zip"
  elif path.endswith(".img"):
    return "img"
  else:
    return "UNKNOWN"

if __name__ == "__main__":
  if len(sys.argv) < 2:
    print("Usage: %s [zip file or boot.img]" % sys.argv[0])
    clean_up_and_exit(1)

  filename = sys.argv[1]

  if not os.path.exists(filename):
    print("%s does not exist!" % filename)
    clean_up_and_exit(1)

  filename = os.path.abspath(filename)
  filetype = detect_file_type(filename)
  fileinfo = get_file_info(filename)

  if filetype == "UNKNOWN":
    print("Unsupported file")
    clean_up_and_exit(1)

  if filetype == "zip":
    if not fileinfo:
      print("Unsupported zip")
      clean_up_and_exit(1)

    newfile = patch_zip(filename, fileinfo)
    print("Successfully patched zip")
    newpath = re.sub(r"\.zip$", "_dualboot.zip", filename)
    shutil.move(newfile, newpath)
    print("Path: " + newpath)

  elif filetype == "img":
    newfile = patch_boot_image(filename, fileinfo)
    print("Successfully patched boot image")
    newpath = re.sub(r"\.img$", "_dualboot.img", filename)
    shutil.move(newfile, newpath)
    print("Path: " + newpath)

  clean_up_and_exit(0)
