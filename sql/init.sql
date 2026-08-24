-- Optional reference schema. The FastAPI app creates these tables automatically
-- on startup via SQLAlchemy, so running this file by hand is not required -
-- it's here so you can inspect/version the schema or set it up ahead of time.

CREATE DATABASE IF NOT EXISTS expense_tracker
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE expense_tracker;

CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(50)  NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role          VARCHAR(20)  NOT NULL,        -- head | hr | employee
  display_name  VARCHAR(100) NOT NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS expenses (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  employee_id       VARCHAR(50)  NOT NULL,
  employee_name     VARCHAR(100) NOT NULL,
  type              VARCHAR(50)  NOT NULL,
  data              JSON         NOT NULL,
  status            VARCHAR(20)  NOT NULL DEFAULT 'Pending',
  created_date      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  submitted_date    DATETIME     NULL,
  decided_by        VARCHAR(100) NULL,
  decided_date      DATETIME     NULL,
  rejection_reason  TEXT         NULL,
  FOREIGN KEY (employee_id) REFERENCES users(username),
  INDEX idx_expenses_employee (employee_id),
  INDEX idx_expenses_status (status),
  INDEX idx_expenses_type (type)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS expense_history (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  expense_id  INT NOT NULL,
  at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  by          VARCHAR(100),
  action      VARCHAR(255),
  note        TEXT NULL,
  FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE,
  INDEX idx_history_expense (expense_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS files (
  id             VARCHAR(64)  PRIMARY KEY,
  expense_id     INT NULL,
  field_key      VARCHAR(50)  NULL,
  filename       VARCHAR(255) NOT NULL,
  content_type   VARCHAR(100) NOT NULL,
  size           INT NOT NULL,
  storage_path   VARCHAR(500) NOT NULL,
  uploaded_by    VARCHAR(50)  NULL,
  uploaded_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE,
  INDEX idx_files_expense (expense_id)
) ENGINE=InnoDB;
