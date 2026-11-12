// Command fake is the single executable behind every fakebin binary name.
package main

import (
	"os"

	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func main() {
	os.Exit(fakebin.Run(os.Args[0], os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}
