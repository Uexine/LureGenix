-- Сброс пароля admin на "password" (если был 401 при входе).
-- Запуск: docker exec -i luregenix-postgres-1 psql -U admin -d luregenix < db/update_admin_password.sql
UPDATE admins
SET password_hash = '$2b$12$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi'
WHERE username = 'admin';
