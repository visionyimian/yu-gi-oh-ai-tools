package main

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestGetBasePath(t *testing.T) {
	tests := []struct {
		name        string
		useXDG      bool
		withLegacy  bool
		assertExact bool
	}{
		// An explicit override must win even when the legacy directory exists.
		{name: "XDG_CONFIG_HOME wins", useXDG: true, withLegacy: true, assertExact: true},
		// Existing installations keep their database instead of re-downloading it.
		// On Linux the platform default happens to be the legacy path as well, so this
		// case mainly guards macOS and the priority against the fallback.
		{name: "legacy path is preserved", useXDG: false, withLegacy: true, assertExact: true},
		// The regression: without $XDG_CONFIG_HOME and $HOME (the normal Windows
		// situation) the old implementation returned the relative ".config/ygo-db",
		// which made the ~100 MB cache follow the current working directory.
		{name: "fallback is an absolute platform directory", useXDG: false, withLegacy: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			home := t.TempDir()
			xdg := filepath.Join(t.TempDir(), "xdg")
			legacy := filepath.Join(home, ".config", "ygo-db")

			// $USERPROFILE is what os.UserHomeDir reads on Windows, $HOME on Unix.
			t.Setenv("HOME", home)
			t.Setenv("USERPROFILE", home)
			t.Setenv("XDG_CONFIG_HOME", "")
			if tt.useXDG {
				t.Setenv("XDG_CONFIG_HOME", xdg)
			}
			if tt.withLegacy {
				require.NoError(t, os.MkdirAll(legacy, 0o755))
			}

			got := getBasePath()

			switch {
			case tt.useXDG:
				assert.Equal(t, filepath.Join(xdg, "ygo-db"), got)
			case tt.withLegacy:
				assert.Equal(t, legacy, got)
			default:
				assert.True(t, filepath.IsAbs(got), "base path must be absolute, got %q", got)
				assert.Equal(t, "ygo-db", filepath.Base(got))
			}
		})
	}
}
