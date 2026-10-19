package main

import (
	"fmt"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"slices"

	"github.com/spf13/cobra"

	"github.com/elmhuangyu/yu-gi-oh-ai-tools/ygo-db/cmd/ygo-db-cli/commands"
	"github.com/elmhuangyu/yu-gi-oh-ai-tools/ygo-db/lib/cdb"
	"github.com/elmhuangyu/yu-gi-oh-ai-tools/ygo-db/lib/git"
)

const (
	cdbRepoURL = "https://github.com/mycard/ygopro-database.git"
)

var (
	flagLang string
	db       *cdb.DB
	gitRepo  *git.Repo
)

// getBasePath returns the directory that caches the ygopro-database clone.
//
// Resolution order:
//  1. $XDG_CONFIG_HOME/ygo-db — explicit override, honoured on every platform.
//  2. $HOME/.config/ygo-db    — legacy location, kept when it is already populated
//     so that existing installations do not re-download the database.
//  3. platform default        — os.UserCacheDir() on Windows (%LocalAppData%), otherwise
//     os.UserConfigDir() ($HOME/.config on Linux, ~/Library/Application Support on macOS).
//
// Windows defines neither $HOME nor $XDG_CONFIG_HOME by default, so the previous
// implementation resolved to the relative path ".config/ygo-db" and silently moved the
// ~100 MB cache along with the current working directory.
func getBasePath() string {
	if xdg := os.Getenv("XDG_CONFIG_HOME"); xdg != "" {
		return filepath.Join(xdg, "ygo-db")
	}

	if home, err := os.UserHomeDir(); err == nil {
		legacy := filepath.Join(home, ".config", "ygo-db")
		if _, err := os.Stat(legacy); err == nil {
			return legacy
		}
	}

	// The database is a re-downloadable clone, so prefer the cache directory on
	// Windows: %LocalAppData% is not roamed to the domain profile like %AppData% is.
	if runtime.GOOS == "windows" {
		if dir, err := os.UserCacheDir(); err == nil {
			return filepath.Join(dir, "ygo-db")
		}
	}
	if dir, err := os.UserConfigDir(); err == nil {
		return filepath.Join(dir, "ygo-db")
	}

	// os.UserConfigDir only fails when neither $HOME nor $XDG_CONFIG_HOME is set on
	// Unix; fall back to the historical relative path as a last resort.
	return filepath.Join(".config", "ygo-db")
}

var rootCmd = &cobra.Command{
	Use:   "ygo-db-cli",
	Short: "A CLI tool to query Yu-Gi-Oh! card database",
}

func init() {
	rootCmd.PersistentFlags().StringVar(
		&flagLang,
		"lang",
		cdb.SupportLanguages[0],
		fmt.Sprintf("Language for card data: %v", cdb.SupportLanguages))

	rootCmd.AddCommand(commands.GetCardByIDCmd)
	rootCmd.AddCommand(commands.GetCardsByNameCmd)
	rootCmd.AddCommand(commands.GetCardsByArchetypesCmd)
	rootCmd.AddCommand(commands.GetCardsByYDKCmd)

	rootCmd.PersistentPreRunE = func(cmd *cobra.Command, args []string) error {
		// Validate lang flag
		validLang := slices.Contains(cdb.SupportLanguages, flagLang)
		if !validLang {
			return fmt.Errorf("invalid language: %s (supported: %v)", flagLang, cdb.SupportLanguages)
		}

		basePath := getBasePath()

		var err error
		gitRepo = git.NewRepo(basePath, cdbRepoURL)
		if err = gitRepo.EnsureRepoUpToDate(); err != nil {
			log.Printf("cdb repo failed to update: %v", err)
		}

		db, err = cdb.New(basePath, flagLang)
		if err != nil {
			return err
		}

		// Set db instance for commands
		commands.SetDB(db)

		return nil
	}
}

func main() {
	if err := rootCmd.Execute(); err != nil {
		log.Fatalf("command execution failed: %v", err)
	}
}
