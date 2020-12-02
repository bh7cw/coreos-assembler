package main

/*
	Definition for the "remote" command.
*/

import (
	"fmt"
	"github.com/coreos/gangplank/ocp"
	"github.com/coreos/gangplank/remote"
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
	"os"
	"path/filepath"
)

var (
	containBuilds bool
	jobSpec       string
	buildSteps    string
	localCosaDir  string

	cmdRemote = &cobra.Command{
		Use:   "remote",
		Short: "Run cosa gangplank commands remotely",
		Run:   runRemote,
	}
)

func init() {
	cmdRoot.AddCommand(cmdRemote)
	cmdRemote.Flags().BoolVarP(&containBuilds, "containBuilds", "c", false, "contain builds or not")
	cmdRemote.Flags().StringVarP(&jobSpec, "jobSpec", "j", "", "location of the jobSpec")
	cmdRemote.Flags().StringVarP(&buildSteps, "buildSteps", "b", "", "location of the build.steps")
	cmdRemote.Flags().StringVarP(&localCosaDir, "localCosaDir", "l", "", "location of the local cosa source")

	if localCosaDir == "" {
		path, err := os.Getwd()
		if err != nil {
			localCosaDir = cosaContainerDir
		} else {
			localCosaDir = filepath.Dir(path)
		}
	}
}

func runRemote(c *cobra.Command, args []string) {
	// check that the cosa dir exists
	_, err := os.Stat(localCosaDir)
	if os.IsNotExist(err) {
		log.Fatalf("cosaDir: %s does not exist", localCosaDir)
	}

	// check the cosa dir includes the expected directories
	dirs := [...]string{"src", "overrides", "builds", "tmp", "cache"}
	for _, d := range dirs {
		dir := fmt.Sprintf("%s/%s", localCosaDir, d)
		_, err := os.Stat(dir)
		if os.IsNotExist(err) {
			log.Fatalf("%s does not exist", dir)
		}
	}

	// includes contains the directories and files used to create the archive
	var includes []string

	srcDir := fmt.Sprintf("%s/%s", localCosaDir, "src")
	includes = append(includes, srcDir)

	overridesDir := fmt.Sprintf("%s/%s", localCosaDir, "overrides")
	includes = append(includes, overridesDir)

	if containBuilds {
		buildsDir := fmt.Sprintf("%s/%s", localCosaDir, "builds")
		includes = append(includes, buildsDir)
	}

	if jobSpec != "" {
		_, err := os.Stat(jobSpec)
		if os.IsNotExist(err) {
			log.Fatalf("%s does not exist!\n", jobSpec)
		}
		includes = append(includes, jobSpec)
	}

	if buildSteps != "" {
		_, err := os.Stat(buildSteps)
		if os.IsNotExist(err) {
			log.Fatalf("%s does not exist!\n", buildSteps)
		}
		includes = append(includes, buildSteps)
	}

	// dest is the target archive file
	dest := fmt.Sprintf("%s/devel.tar", localCosaDir)

	// emptyDirs includes the directory names to create empty directories in the archive
	var emptyDirs []string
	emptyDirs = append(emptyDirs, "tmp")
	emptyDirs = append(emptyDirs, "cache")
	if !containBuilds {
		emptyDirs = append(emptyDirs, "builds")
	}

	a := remote.CosaArchive{
		CreateDirs: emptyDirs,
		Includes:   includes,
	}
	if err := a.CreateArchive(dest); err != nil {
		log.Fatalf("failed to create the tar ball: %v", err)
	}

	// create a cluster that uses podman
	cluster := ocp.NewCluster(false, "")
	cluster.SetPodman(cosaSrvDir)

	// pass the archive file to the cluster
	f, err := os.Open(dest)
	if err != nil {
		log.Fatalf("failed to open the archive %v: %v", dest, err)
	}
	cluster.SetStdIO(f, os.Stdout, os.Stderr)

	clusterCtx := ocp.NewClusterContext(ctx, cluster)
	if jobSpec != "" {
		specFile = jobSpec
	}
	// define the pod
	pb, err := ocp.NewPodBuilder(clusterCtx, cosaOverrideImage, serviceAccount, specFile, cosaWorkDir)
	if err != nil {
		log.Fatalf("failed to define builder pod: %v", err)
	}

	// start the buildconfig
	if err := pb.Exec(clusterCtx); err != nil {
		log.Fatalf("failed to execute CI builder: %v", err)
	}
}
