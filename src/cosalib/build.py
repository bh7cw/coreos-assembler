"""
Provides a base abstration class for build reuse.
"""

import logging as log
import os
import os.path
import shutil
import tempfile

from cosalib.cmdlib import (
    get_basearch,
    load_json,
    sha256sum_file,
    write_json)
from cosalib.builds import Builds


# BASEARCH is the current machine architecture
BASEARCH = get_basearch()


class BuildError(Exception):
    """
    Base error for build issues.
    """
    pass


class BuildExistsError(BuildError):
    """
    Thrown when a build already exists
    """
    pass


class _Build:
    """
    The Build Class handles the reading in and return of build JSON emitted
    as part of the build process.

    The following must be implemented to create a valid Build class:
      - _build_artifacts(*args, **kwargs)
    """

    def __init__(self, *args, **kwargs):
        """
        init loads the builds.json which lists the builds, loads the relevant
        meta-data from JSON and finally, locates the build artifacts.

        :param builds_dir: name of directory to find the builds
        :type builds_dir: str
        :param build: build id or "latest" to parse
        :type build: str
        :param workdir: Temporary directory to ensure exists and is clean
        :type workdir: None or str
        :raises: BuildError

        If the build meta-data fails to parse, then a generic exception is
        raised.

        If workdir is None then no temporary work directory is created.
        """
        build = kwargs.get("build", "latest")
        builds = Builds(os.path.dirname(build))
        if build != "latest":
            if not builds.has(build):
                raise BuildError("Build was not found in builds.json")
        else:
            build = builds.get_latest()

        log.info("Targeting build: %s", build)
        self._build_dir = builds.get_build_dir(
            build,
            basearch=kwargs.get("arch", BASEARCH)
        )

        self._build_json = {
            "commit": None,
            "config": None,
            "image": None,
            "meta": None
        }
        self._found_files = {}
        self._workdir = kwargs.get("workdir", os.getcwd())
        self._tmpdir = tempfile.mkdtemp(prefix="build_tmpd")

        os.environ['workdir'] = self._workdir
        os.environ['TMPDIR'] = os.path.join(self._workdir, "tmp")

        # Check to make sure that the build and it's meta-data can be parsed.
        emsg = "was not read in properly or is not defined"
        if self.commit is None:
            raise BuildError("%s %s" % self.__file("commit"), emsg)
        if self.config is None:
            raise BuildError("%s %s" % self.__file("config"), emsg)
        if self.image is None:
            raise BuildError("%s %s" % self.__file("image"), emsg)
        if self.meta is None:
            raise BuildError("%s %s" % self.__file("meta"), emsg)

        self._image_name = None

        log.info("Proccessed build for: %s (%s-%s) %s",
                 self.summary, self.build_name.upper(), self.basearch,
                 self.build_id)

    def __del__(self):
        try:
            shutil.rmtree(self._tmpdir)
        except Exception as e:
            raise Exception(
                f"failed to remove temporary directory: {self._tmpdir}", e)

    def clean(self):
        """
        Removes the temporary work directory.
        """
        if self._workdir is not None:
            shutil.rmtree(self._workdir)
            log.info(
                'Removed temporary work directory at {}'.format(self.workdir))

    @property
    def workdir(self):
        """ get the temporary work directory """
        return self._workdir

    @property
    def tmpdir(self):
        """ get the tempdir for this build object """
        return self._tmpdir

    @property
    def build_id(self):
        """ get the build id, e.g. 99.33 """
        return self.get_meta_key("meta", "buildid")

    @property
    def build_dir(self):
        """ return the actual path for the build root """
        return self._build_dir

    @property
    def build_name(self):
        """ get the name of the build """
        return str(self.get_meta_key("meta", "name"))

    @property
    def summary(self):
        """ get the summary of the build """
        return self.get_meta_key("meta", "summary")

    @property
    def commit(self):
        """ get the commitmeta.json dict """
        if self._build_json["commit"] is None:
            self._build_json["commit"] = self.__get_json("commit")
        return self._build_json["commit"]

    @property
    def ostree_commit(self):
        """ get the builds' ostree commit """
        return self.meta.get('ostree-commit')

    @property
    def config(self):
        """ get the the meta-data about the config recipe """
        if self._build_json["config"] is None:
            self._build_json["config"] = self.__get_json("config")
        return self._build_json["config"]

    @property
    def image(self):
        """ get the meta-data about the COSA image """
        if self._build_json["image"] is None:
            self._build_json["image"] = self.__get_json("image")
        return self._build_json["image"]

    @property
    def meta(self):
        """ get the meta.json dict """
        if self._build_json["meta"] is None:
            self._build_json["meta"] = self.__get_json("meta")
        return self._build_json["meta"]

    def refresh_meta(self):
        """
        Refresh the meta-data from disk. This is useful when the on-disk
        meta-data may have been updated.
        """
        self._build_json["meta"] = self.__get_json("meta")

    @property
    def basearch(self):
        return self.meta.get(_Build.ckey("coreos-assembler.basearch"),
                             BASEARCH)

    def ensure_built(self):
        if not self.have_artifact:
            self.build_artifacts()

    @property
    def image_name_base(self):
        """
        Get the name of the image.
        """
        if self._image_name is not None:
            return self._image_name

        return (f'{self.build_name}-{self.build_id}'
                f'-{self.platform}.{self.basearch}')

    @staticmethod
    def ckey(var):
        """
        Short-hand helper to get coreos-assembler values from json.

        :param var: postfix string to append
        :type var: str
        :returns: str
        """
        return "coreos-assembler.%s" % var

    def __file(self, var):
        """
        Look up the file location for specific files.
        The lookup is performed against the specific build root.

        :param var: name of file to return
        :type var: str
        :returns: string
        :raises: KeyError
        """
        lookup = {
            "commit": "%s/commitmeta.json" % self.build_dir,
            "config": ("%s/coreos-assembler-config-git.json" % self.build_dir),
            "image": "/cosa/coreos-assembler-git.json",
            "meta": "%s/meta.json" % self.build_dir,
        }
        return lookup[var]

    def __get_json(self, name):
        """
        Read in the json file in, and decode it.

        :param name: name of the json file to read-in
        :type name: str
        :returns: dict
        """
        file_path = self.__file(name)
        log.debug("Reading in %s", file_path)
        return load_json(file_path)

    def get_obj(self, key):
        """
        Return the backing object

        :param key: name of the meta-data key to return
        :type key: str
        :returns: dict
        :raises: BuildError

        Returns the meta-data dict of the parsed JSON.
        """
        lookup = {
            "commit": self.commit,
            "config": self.config,
            "image": self.image,
            "meta": self.meta,
        }
        try:
            return lookup[key]
        except:
            raise BuildError(
                "invalid key %s, valid keys are %s" % (key, lookup.keys()))

    def get_meta_key(self, obj, key):
        """
        Look up a the key in a dict

        :param obj: name of meta-data key to check
        :type obj: str
        :param key: key to look up
        :type key: str
        :returns: dict or str

        Returns the object from the meta-data dict. For example, calling
        get_meta_key("meta", "ref") will give you the build ref from.
        """
        try:
            data = self.get_obj(obj)
            return data[key]
        except KeyError as err:
            log.warning("lookup for key '%s' returned: %s", key, str(err))
            return None

    def get_sub_obj(self, obj, key, sub):
        """
        Return the sub-element sub of key in a nested dict, using get_meta_key.
        This function help exploring nested dicts in meta-data.

        :param obj: name of the meta-data object to lookup
        :type obj: str
        :param key: name of nested dict to lookup
        :type key: str
        :param sub: name of the key in nested dict to lookup
        :type stub: str
        :returns: obj
        """
        if isinstance(obj, str):
            obj = self.get_obj(obj)
            return self.get_sub_obj(obj, key, sub)
        try:
            return obj[key][sub]
        except KeyError:
            log.warning(obj)

    def meta_append(self, update_dict):
        """
        Updates the internal meta structure.

        :param update_dict: The dictionary to append into meta.
        :type update_dict: dict
        """
        self._build_json["meta"].update(update_dict)

    def meta_write(self):
        """
        Writes out the meta.json file based on the internal structure.
        """
        write_json(self.__file("meta"), self._build_json["meta"])

    def build_artifacts(self, *args, **kwargs):
        """
        Wraps and executes _build_artifacts.

        :param args: All non-keyword arguments
        :type args: list
        :param kwargs: All keyword arguments
        :type kwargs: dict
        :raises: NotImplementedError
        """
        log.info("Processing the build artifacts")
        self._build_artifacts(*args, **kwargs)
        log.info("Finished building artifacts")
        if len(self._found_files.keys()) == 0:
            log.warn("There were no files found after building")

    def _build_artifacts(self, *args, **kwargs):
        """
        Implements the building of artifacts.
        Must be overriden by child class and must populate the
        _found_files dictionary.

        :param args: All non-keyword arguments
        :type args: list
        :param kwargs: All keyword arguments
        :type kwargs: dict
        :raises: NotImplementedError
        """
        raise NotImplementedError("_build_artifacts must be overriden")

    @property
    def image_name(self):
        if self._image_name is None:
            raise NotImplementedError("image naming is not implmented here")
        return self._image_name

    @image_name.setter
    def image_name(self, val):
        self._image_name = val

    @property
    def image_path(self):
        return os.path.join(self.build_dir, self.image_name)

    @property
    def have_artifact(self):
        if os.path.exists(self.image_path):
            return True
        return False

    def get_artifact_meta(self, fname=None):
        fsize = '{}'.format(os.stat(self.image_path).st_size)
        if fname is None:
            fname = self.image_name
        fpath = os.path.join(self.build_dir, fname)
        log.info(f"Calculating metadata for {fname}")
        return {
            "path": fname,
            "sha256sum": sha256sum_file(fpath),
            "size": int(fsize)
        }

    def get_artifacts(self):
        """ Iterator for the meta-data about artifacts in the build root """
        for name in self._found_files:
            yield (name, self._found_files[name])
