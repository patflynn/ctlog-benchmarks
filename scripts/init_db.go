package main

import (
	"database/sql"
	"io"
	"log"
	"net/http"
	"os"
	"strings"

	_ "github.com/go-sql-driver/mysql"
)

func main() {
	if len(os.Args) < 2 {
		log.Fatal("Usage: init_db <dsn>")
	}
	dsn := os.Args[1]

	log.Println("Downloading Trillian schema...")
	resp, err := http.Get("https://raw.githubusercontent.com/google/trillian/master/storage/mysql/schema/storage.sql")
	if err != nil {
		log.Fatalf("Failed to download schema: %v", err)
	}
	defer resp.Body.Close()
	schema, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Fatalf("Failed to read schema: %v", err)
	}

	log.Println("Connecting to database...")
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		log.Fatalf("Failed to open db: %v", err)
	}
	defer db.Close()

	if err := db.Ping(); err != nil {
		log.Fatalf("Failed to ping db: %v", err)
	}

	log.Println("Applying schema...")
	stmts := strings.Split(string(schema), ";")
	for _, stmt := range stmts {
		stmt = strings.TrimSpace(stmt)
		if stmt == "" {
			continue
		}
		// Basic naive split, works for Trillian schema which is simple
		if _, err := db.Exec(stmt); err != nil {
			// Ignore "Table exists" (Error 1050)
			if strings.Contains(err.Error(), "1050") {
				continue
			}
			log.Printf("Warning executing statement: %v", err)
		}
	}
	log.Println("Database schema initialized successfully.")
}
