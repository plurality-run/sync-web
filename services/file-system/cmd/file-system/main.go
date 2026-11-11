package main

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"os"

	"github.com/plurality-run/sync-web/services/file-system/internal/config"
	"github.com/plurality-run/sync-web/services/file-system/internal/gateway"
	"github.com/plurality-run/sync-web/services/file-system/internal/webdav"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		slog.Error("failed to load configuration", "error", err)
		os.Exit(1)
	}

	if len(os.Args) > 1 && os.Args[1] == "--healthcheck" {
		if err := runHealthcheck(cfg.Address); err != nil {
			slog.Error("healthcheck failed", "error", err)
			os.Exit(1)
		}
		return
	}

	webdavHandler := webdav.Handler{
		Gateway:        gateway.New(cfg.GatewayBaseURL),
		MaxObjectBytes: cfg.MaxObjectBytes,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", health)
	mux.Handle("/webdav", webdavHandler)
	mux.Handle("/webdav/", webdavHandler)

	slog.Info("starting file-system service", "address", cfg.Address, "gatewayBaseUrl", cfg.GatewayBaseURL, "maxObjectBytes", cfg.MaxObjectBytes)
	if err := http.ListenAndServe(cfg.Address, mux); err != nil {
		slog.Error("server stopped", "error", err)
		os.Exit(1)
	}
}

func health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func runHealthcheck(address string) error {
	url := "http://127.0.0.1" + address + "/health"
	if address == "" || address[0] != ':' {
		url = "http://" + address + "/health"
	}
	resp, err := http.Get(url) //nolint:gosec // local container health probe
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return http.ErrNoLocation
	}
	return nil
}
