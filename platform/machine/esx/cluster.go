// Copyright 2016 CoreOS, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package esx

import (
	"fmt"
	"math/rand"
	"os"
	"path/filepath"

	"github.com/coreos/pkg/capnslog"

	"github.com/coreos/mantle/platform"
	"github.com/coreos/mantle/platform/api/esx"
	"github.com/coreos/mantle/platform/conf"
)

const (
	Platform platform.Name = "esx"
)

var (
	plog = capnslog.NewPackageLogger("github.com/coreos/mantle", "platform/machine/esx")
)

type cluster struct {
	*platform.BaseCluster
	api *esx.API
}

// NewCluster creates an instance of a Cluster suitable for spawning
// instances on VMware ESXi vSphere platform.
func NewCluster(opts *esx.Options, rconf *platform.RuntimeConfig) (platform.Cluster, error) {
	api, err := esx.New(opts)
	if err != nil {
		return nil, err
	}

	bc, err := platform.NewBaseCluster(opts.BaseName, rconf, Platform, "")
	if err != nil {
		return nil, err
	}

	ec := &cluster{
		BaseCluster: bc,
		api:         api,
	}

	return ec, nil
}

func (ec *cluster) vmname() string {
	b := make([]byte, 5)
	rand.Read(b)
	return fmt.Sprintf("%s-%x", ec.Name(), b)
}

func (ec *cluster) NewMachine(userdata *conf.UserData) (platform.Machine, error) {
	conf, err := ec.RenderUserData(userdata, map[string]string{
		"$public_ipv4":  "${COREOS_ESX_IPV4_PUBLIC_0}",
		"$private_ipv4": "${COREOS_ESX_IPV4_PRIVATE_0}",
	})
	if err != nil {
		return nil, err
	}

	conf.AddSystemdUnit("coreos-metadata.service", `[Unit]
Description=VMware metadata agent

[Service]
Type=oneshot
Environment=OUTPUT=/run/metadata/coreos
ExecStart=/usr/bin/mkdir --parent /run/metadata
ExecStart=/usr/bin/bash -c 'echo "COREOS_ESX_IPV4_PRIVATE_0=$(ip addr show ens192 | grep -Po "inet \K[\d.]+")\nCOREOS_ESX_IPV4_PUBLIC_0=$(ip addr show ens192 | grep -Po "inet \K[\d.]+")" > ${OUTPUT}'`, false)

	instance, err := ec.api.CreateDevice(ec.vmname(), conf)
	if err != nil {
		return nil, err
	}

	mach := &machine{
		cluster: ec,
		mach:    instance,
	}

	mach.dir = filepath.Join(ec.RuntimeConf().OutputDir, mach.ID())
	if err := os.Mkdir(mach.dir, 0777); err != nil {
		mach.Destroy()
		return nil, err
	}

	confPath := filepath.Join(mach.dir, "user-data")
	if err := conf.WriteFile(confPath); err != nil {
		mach.Destroy()
		return nil, err
	}

	if mach.journal, err = platform.NewJournal(mach.dir); err != nil {
		mach.Destroy()
		return nil, err
	}

	if err := platform.StartMachine(mach, mach.journal); err != nil {
		mach.Destroy()
		return nil, err
	}

	ec.AddMach(mach)

	return mach, nil
}
