-- Schema only, no production records or credentials.

CREATE TABLE `CarList` (
	`ID` INTEGER NOT NULL AUTO_INCREMENT, 
	client_id VARCHAR(20), 
	license_plate VARCHAR(20) NOT NULL, 
	car_type VARCHAR(100) NOT NULL, 
	type_code VARCHAR(100), 
	holder VARCHAR(100), 
	notes VARCHAR(500), 
	amount VARCHAR(50), 
	contact_person VARCHAR(100), 
	contract_file_uuid TEXT, 
	create_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP, 
	equipment VARCHAR(255), 
	isdelete TINYINT(1) DEFAULT '0', 
	license_file_uuid TEXT, 
	manager VARCHAR(100), 
	owner VARCHAR(100), 
	passengers VARCHAR(100), 
	phone_number VARCHAR(30), 
	purchase_date VARCHAR(100), 
	vehicle_data_file_uuid TEXT, 
	PRIMARY KEY (`ID`)
)ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci DEFAULT CHARSET=utf8mb4

;

CREATE TABLE `EquipmentList` (
	id INTEGER NOT NULL COMMENT '主鍵編號' AUTO_INCREMENT, 
	equipment_id VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '儀器設備編碼', 
	equipment_loc VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '工具位置編號', 
	equipment_name VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '工具名稱', 
	equipment_plus TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '配件清單', 
	brand_manufacturer VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '品牌廠商', 
	purchase_manufacturer VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '購買廠商', 
	fix_manufacturer VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '維護廠商', 
	quantity INTEGER COMMENT '數量' DEFAULT '1', 
	purpose VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '用途說明', 
	holder VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '保管人', 
	notes TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '備註', 
	hold_adv ENUM('列管','不列管','停用') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '列管建議' DEFAULT '列管', 
	estimated_amount DECIMAL(10, 0) COMMENT '預估價值', 
	fix_date DATE COMMENT '委外校正日期', 
	valid_period DATE COMMENT '有效期限', 
	is_deleted TINYINT(1) COMMENT '是否已刪除' DEFAULT '0', 
	created_at TIMESTAMP NULL COMMENT '建立時間' DEFAULT CURRENT_TIMESTAMP, 
	updated_at TIMESTAMP NULL COMMENT '更新時間' DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
)COMMENT='儀器設備基本資料表' COLLATE utf8mb4_unicode_ci ENGINE=InnoDB DEFAULT CHARSET=utf8mb4

;

CREATE TABLE cost (
	sn BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	type VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	reason VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	amount VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	plate VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	isdelete TINYINT(1) NOT NULL DEFAULT '0', 
	upload_file TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	notes VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	PRIMARY KEY (sn)
)ENGINE=InnoDB COLLATE utf8mb4_unicode_ci DEFAULT CHARSET=utf8mb4

;

CREATE TABLE form_flows (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	form_id VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '表單ID，關聯formio_responses.form_id', 
	status VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '狀態：lending=借用中, returned=已歸還' DEFAULT 'lending', 
	created_at DATETIME COMMENT '建立時間' DEFAULT CURRENT_TIMESTAMP, 
	updated_at DATETIME COMMENT '更新時間' DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, 
	contact_person VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	PRIMARY KEY (id)
)COMMENT='表單流程狀態表' COLLATE utf8mb4_unicode_ci ENGINE=InnoDB DEFAULT CHARSET=utf8mb4

;

CREATE TABLE formio_responses (
	sn INTEGER NOT NULL AUTO_INCREMENT, 
	form_id VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '表單ID，格式：年月類型序號', 
	reason VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '事由/原因', 
	place VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '地點', 
	start DATETIME NOT NULL COMMENT '開始時間', 
	end DATETIME NOT NULL COMMENT '結束時間', 
	plate VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '車牌號碼', 
	employees TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '員工清單，逗號分隔', 
	`applicant_ID` VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '申請人ID', 
	is_deleted TINYINT(1) COMMENT '是否已刪除，0=否，1=是' DEFAULT '0', 
	created_at TIMESTAMP NULL COMMENT '建立時間' DEFAULT CURRENT_TIMESTAMP, 
	updated_at TIMESTAMP NULL COMMENT '更新時間' DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, 
	PRIMARY KEY (sn)
)COMMENT='表單回應資料表' COLLATE utf8mb4_unicode_ci ENGINE=InnoDB DEFAULT CHARSET=utf8mb4

;

CREATE TABLE garage_files (
	sn BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	plate VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	notes TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	attachment_uuids TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	isdelete TINYINT(1) NOT NULL DEFAULT '0', 
	PRIMARY KEY (sn)
)ENGINE=InnoDB COLLATE utf8mb4_unicode_ci DEFAULT CHARSET=utf8mb4

;

CREATE TABLE insurance_records (
	sn BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	company VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	validity_period VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	plate VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	company_phone VARCHAR(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	employee VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	employee_phone VARCHAR(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	roadside_assistance VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	policy_file_uuid TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	claim_file_uuid TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	isdelete TINYINT(1) NOT NULL DEFAULT '0', 
	PRIMARY KEY (sn)
)ENGINE=InnoDB COLLATE utf8mb4_unicode_ci DEFAULT CHARSET=utf8mb4

;

CREATE TABLE vehicle_managers (
	sn BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	plate VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	manager_name VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	notes TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	isdelete TINYINT(1) NOT NULL DEFAULT '0', 
	PRIMARY KEY (sn)
)ENGINE=InnoDB COLLATE utf8mb4_unicode_ci DEFAULT CHARSET=utf8mb4

;

CREATE TABLE vehicle_records (
	sn BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	plate VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	data_type VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	record_type VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	record_date VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, 
	notes TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '備註', 
	attachment_uuids TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci, 
	create_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, 
	isdelete TINYINT(1) NOT NULL DEFAULT '0', 
	PRIMARY KEY (sn)
)ENGINE=InnoDB COLLATE utf8mb4_unicode_ci DEFAULT CHARSET=utf8mb4

;