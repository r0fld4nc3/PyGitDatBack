# PyGitDatBack
 A simple way to locally backup GitHub repositories.

 # Launching
 Requires [uv](https://docs.astral.sh/uv/getting-started/installation/). It installs the right Python version and the dependencies on first launch.

 Once cloned, launching can be done via the launch.sh file.
 Ensure it is runnable as a programme.
 
 ```bash
 chmod +x launch.sh
 ```

 Once in the directory it can also be launched with
 ```bash
 ./launch.sh
 ```

 Arguments are passed on to the app, e.g. `./launch.sh --debug` for debug logging.

 # Backups
 Each repository is backed up to `<backup root>/<owner>/<repository>.git`.
 This is a bare git repository: it holds every commit, branch and tag, but no checked-out files.

 Nothing already backed up is ever dropped:
 * Branches and tags deleted on GitHub stay in the backup.
 * If a branch is force-pushed or a tag is moved, the previous version is kept under `refs/preserved/<timestamp>/`.

 ## Restoring
 Get a normal working copy, with files, from a backup:
 ```bash
 git clone <backup root>/<owner>/<repository>.git <repository>
 ```

 ## Recovering overwritten history
 List versions kept after a force-push or moved tag:
 ```bash
 git -C <backup root>/<owner>/<repository>.git for-each-ref refs/preserved/
 ```

 Turn one into a branch, then clone as above to see it:
 ```bash
 git -C <backup root>/<owner>/<repository>.git branch recovered-main refs/preserved/<timestamp>/heads/main
 ```
