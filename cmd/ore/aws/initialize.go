// Copyright 2017 CoreOS, Inc.
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

package aws

import (
	"fmt"
	"net/url"

	"github.com/spf13/cobra"
)

var (
	cmdInitialize = &cobra.Command{
		Use:   "initialize",
		Short: "initialize any uncreated resources for a given aws region",
		RunE:  runInitialize,
	}

	bucket string
)

func init() {
	AWS.AddCommand(cmdInitialize)
	cmdInitialize.Flags().StringVar(&bucket, "bucket", "", "the s3 bucket URI to initialize; will default to a regional bucket")
}

func runInitialize(cmd *cobra.Command, args []string) error {
	bucket, err := defaultBucket(bucket, region)
	if err != nil {
		return fmt.Errorf("invalid bucket: %v", err)
	}

	bucketURI, err := url.Parse(bucket)
	if err != nil {
		return fmt.Errorf("invalid bucket: %v", err)
	}

	bucketName := bucketURI.Host

	err = API.InitializeBucket(bucketName)
	if err != nil {
		return fmt.Errorf("could not initialize bucket %v: %v", bucketName, err)
	}

	err = API.CreateImportRole(bucketName)
	if err != nil {
		return fmt.Errorf("could not create import role for %v: %v", bucketName, err)
	}
	return nil
}
