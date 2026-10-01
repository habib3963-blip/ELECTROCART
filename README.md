⚡ ELECTROCART MW

Next-Generation Electronics E-Commerce Web Application

A structured Django-based electronics marketplace focused on product discovery, catalogue management, shopping workflows, and scalable catalogue automation.      ---

📌 Project Overview

ELECTROCART MW is a full-stack electronics e-commerce web application developed with Python and Django. The project is designed around a structured product catalogue rather than a simple collection of static product cards. It provides a foundation for managing products, brands, categories, images, variants, specifications, inventory, pricing, shopping cart operations, checkout, orders, offers, reviews, and invoices. A major development goal of ELECTROCART MW is to reduce manual catalogue management through reusable import commands, validation tools, and a future universal catalogue ingestion architecture. ---

🎯 Project Goals

✨ Key Features

🛍️ Product Catalogue

• Dynamic electronics product catalogue. • Product name and description management. • Internal product codes. • Real-world model number support. • Brand management. • Category management. • MRP and selling-price management. • Product stock management. • Product rating and review-count fields. • Product badges. • Active/inactive product status.

🖼️ Product Images

• Multiple images per product. • Primary-image support. • Image ordering. • Alternative text. • External image URLs. • Local uploaded image files. • Product-image import workflow.

🎨 Product Variants

• Variant-specific SKU. • Color support. • Storage support. • Custom JSON attributes. • Variant-specific pricing. • Variant-specific stock. • Active/inactive variant status. • Variant selection from the product experience.

📋 Product Specifications

• Structured name/value specifications. • Custom specification fields. • Display ordering. • CSV-based specification importing. • Catalogue validation for specification data.

🔎 Product Discovery

• Product search. • Category filtering. • Price filtering. • Rating filtering. • Product sorting. • Dynamic product cards. • Product detail pages.

🛒 Shopping Experience

• Shopping cart. • Quantity management. • Stock-aware cart operations. • Variant-aware cart items. • Wishlist functionality. • Checkout workflow. • Order creation. • Order items. • Payment and order status handling.

🎟️ Offers & Customer Features

• Coupon/discount system. • Product reviews and ratings. • Order management. • Invoice/receipt generation.

🛠️ Administration

• Django Admin. • Product administration. • Brand administration. • Category administration. • Product-image management. • Product-variant management. • Product-specification management. • Order management. • Catalogue correction and maintenance.

🧱 Technology Stack

Layer

Technology

Backend

Python

Web Framework

Django

Frontend

HTML5, CSS3, JavaScript

UI Styling

Tailwind CSS

Database

SQLite

Image Handling

Pillow / Django ImageField

Data Import

Django Management Commands

Version Control

Git

Repository

GitHub

🏗️ High-Level Architecture

ELECTROCART MW │ ▼ Frontend Interface HTML / CSS / JavaScript │ ▼ Django Views │ ▼ Business Logic │ ▼ Django Models │ ▼ SQLite DB

The application separates presentation, request handling, business logic, and persistent catalogue/order data through Django's architecture. ---

📦 Catalogue Architecture

The catalogue is designed around related entities instead of putting every piece of information into a single product record.

Product ├── Brand ├── Category ├── Product Images ├── Product Variants ├── Specifications └── Offers

This structure makes it easier to extend the catalogue as the project grows. ---

🧾 Product Identity

ELECTROCART uses multiple levels of product identity.

Internal Identity │ └── product_code │ ▼ Real-World Identity │ └── brand + model_number │ ▼ External Source Identity │ └── source + source_product_id

The internal ELECTROCART product code is kept separate from identifiers provided by external catalogue sources. ---

🗂️ Core Data Model

Product

The Product model represents the main catalogue item. Typical data includes:
• Name. • Product code. • Model number. • Brand. • Category. • Description. • MRP. • Selling price. • Rating. • Review count. • Stock. • Badge. • Active status.

Brand

Brands provide reusable product ownership/grouping information.

Category

Categories organize products into discoverable catalogue sections.

ProductImage

ProductImage supports multiple visual representations of a product.

ProductVariant

ProductVariant allows one product to have multiple purchasable configurations.

ProductSpecification

ProductSpecification stores structured technical information as name/value pairs.

ProductOffer

ProductOffer provides a foundation for product-level offers and discounts. ---

🛒 E-Commerce Workflow

Browse Catalogue │ ▼ Search / Filter / Sort │ ▼ Product Details │ ▼ Select Variant │ ▼ Add to Cart │ ▼ Stock Validation │ ▼ Checkout │ ▼ Create Order │ ▼ Payment / Order Status │ ▼ Invoice / Receipt

🔄 Catalogue Import Architecture

A key part of the project is moving toward a source-independent catalogue workflow.

CSV / JSON / API / Dataset / Verified Source │ ▼ Raw Data │ ▼ Normalization │ ▼ Validation │ ▼ Deduplication │ ▼ Database │ ▼ Images / Variants / Specs │ ▼ ELECTROCART MW

The long-term goal is to make the database the application's runtime source of truth while external sources act as controlled import sources. ---

📥 Current Import Commands

The project currently contains dedicated Django management commands for catalogue-related imports.

Product Images

python manage.py import_product_images <csv_file>

Product Variants

python manage.py import_product_variants <csv_file>

Product Specifications

python manage.py import_product_specifications <csv_file>

Catalogue Validation

python manage.py validate_catalogue

These commands help separate data preparation from normal application runtime operations. ---

✅ Catalogue Validation

The catalogue validation command checks important data-quality conditions. Validation areas include:
• Product records. • Product codes. • Price values. • MRP values. • Stock values. • Product images. • Primary-image availability. • Variant SKU values. • Variant pricing. • Variant stock. • Specification names. • Specification values. • Specification ordering.
The validator reports errors and warnings separately. Warnings can identify catalogue records that still need additional content, such as missing product images. ---

🧮 Effective Pricing

🧑‍💻 Development Workflow

A typical development cycle is:

Plan ↓ Update Model / View / Template ↓ Create Migration ↓ Apply Migration ↓ Run Django Check ↓ Test Feature ↓ Validate Catalogue ↓ Commit ↓ Push to GitHub

🗄️ Database & Migrations

Django migrations are used to track changes to the database schema. Typical commands:

python manage.py makemigrations python manage.py migrate python manage.py check

Schema changes are kept under the application's migration directory. ---

🖥️ Installation

1. Clone the Repository

git clone https://github.com/shaikhhabibali/ELECTROCART.git

2. Enter the Project Directory

cd ELECTROCART

3. Create a Virtual Environment

python -m venv venv

4. Activate the Environment

Windows PowerShell:

.\venv\Scripts\Activate.ps1

5. Install Dependencies

Install the packages required by the current project environment. For the current development setup:

pip install django pillow python-dotenv

6. Apply Database Migrations

python manage.py migrate

7. Run System Checks

python manage.py check

8. Start the Development Server

python manage.py runserver

Open:

http://127.0.0.1:8000/

🔐 Environment Configuration

Sensitive configuration should be stored outside source-controlled code. Where environment variables are required, use a local .env file. Example:

.env

Never commit real passwords, API keys, tokens, or other secrets to GitHub. ---

📁 Project Structure

ELECTROCART/ 
│ ├── accounts/
│ ├── store/ 
│   ├── models.py 
│   ├── views.py 
│   ├── admin.py 
│   ├── migrations/ 
│   │ │   ├── management/
│   │   └── commands/
│   │ │   ├── products.csv
│   ├── product_images.csv
│   ├── product_variants.csv
│   └── product_specifications.csv
│ ├── templates/ 
├── static/ 
├── media/
│ ├── manage.py
├── db.sqlite3
└── README.md

The structure will evolve as additional catalogue automation and integration modules are introduced. ---

🧪 Testing & Quality Checks

📊 Current Development Status

Area

Status

Django foundation

✅ Completed

Product model

✅ Completed

Brand management

✅ Completed

Category management

✅ Completed

Product images

✅ Completed

Product variants

✅ Completed

Product specifications

✅ Completed

Product search

✅ Completed

Product filtering

✅ Completed

Product sorting

✅ Completed

Cart workflow

✅ Implemented

Stock validation

✅ Implemented

Wishlist

✅ Implemented

Checkout

🔄 Continuing

Order management

🔄 Continuing

Coupon / discount system

🔄 Continuing

Invoice / receipt

🔄 Continuing

Catalogue validation

✅ Completed

Model-number support

✅ Completed

Universal catalogue importer

🔄 Continuing

Source tracking

⏳ Pending

Data normalization

⏳ Pending

Duplicate detection

⏳ Pending

Automated image pipeline

🔄 Continuing

Large product catalogue

🔄 Continuing

Product comparison

⏳ Pending

External integrations

⏳ Pending

AI features

⏳ Pending

Final screenshots

⏳ Pending

Final demo

⏳ Pending

🚧 Current Development Focus

The current development direction is focused on catalogue quality and automation before moving into larger integrations.

Priority Areas

Complete universal catalogue architecture. 2. Add source metadata and source tracking. 3. Build normalization rules. 4. Add duplicate detection. 5. Improve image automation. 6. Expand the real-product catalogue. 7. Continue frontend integration. 8. Complete remaining checkout/order/invoice testing. 9. Perform final UI/UX refinement. 10. Prepare final documentation and demo material. ---

🧩 Continuing Catalogue Architecture

The next catalogue architecture is intended to support multiple data sources without changing the core Product model for every source. Planned source categories include:

Manufacturer / Verified Source │ ├── API ├── CSV ├── JSON ├── Dataset └── Permitted Web Source

Each source can eventually pass through a common normalization layer. ---

🧹 Data Normalization

Normalization is planned to standardize incoming catalogue records. Examples include:
• Brand-name normalization. • Category normalization. • Price formatting. • Stock formatting. • Model-number cleanup. • Specification formatting. • Image metadata normalization. • Attribute normalization.
This stage is currently pending. ---

🔁 Duplicate Detection

Duplicate detection is planned to prevent the same real-world product from being imported multiple times. Potential identity signals include:

source + source_product_id brand + model_number product_code SKU / variant identity

The final duplicate-resolution strategy is still pending. ---

🖼️ Image Automation

The current system supports ProductImage records and import workflows. The next stage is to automate more of the image pipeline. Planned workflow:

Image Source ↓ URL / File Validation ↓ Primary Image Detection ↓ Image Metadata ↓ ProductImage ↓ Catalogue Validation

Automated image processing remains in progress. ---

🧾 Invoice Development

The invoice system uses ELECTROCART branding and a premium visual structure. The current design includes the fixed:

POWER YOUR POSSIBILITIES

promotional hero. The current invoice implementation intentionally does not add GST/tax. Final real-order synchronization and end-to-end PDF testing remain part of the continuing development work. ---

🔮 Planned Product Experience

Future product-experience work may include:
• Advanced product comparison. • More complete product galleries. • Related products. • Recently viewed products. • Improved product recommendations. • More detailed variant presentation. • Enhanced product discovery.
These items are planned and should not be treated as completed features. ---

🔌 Planned External Integrations

External service integrations are planned for later development. Potential integrations include:
• Payment gateway services. • Shipping and order-tracking services. • Email services. • SMS/OTP services. • Currency/exchange-rate services. • Maps/address services.
These integrations are currently pending unless explicitly marked otherwise in the project implementation. ---

🤖 Planned AI Layer

AI features are planned as a later development phase. Planned capabilities include:

AI Recommendations

Recommend products based on catalogue information and user context.

Smart Search

Allow natural-language product discovery.

AI Shopping Assistant

Example future request:

Coding + gaming laptop under ₹80,000

The assistant could eventually translate the request into structured catalogue filters and recommendations. AI features are currently not started. ---

📸 Screenshots & Demo

Final screenshots and the final demonstration section are intentionally reserved for a later project stage. Planned screenshots include:
• Home page. • Product catalogue. • Product details. • Product variants. • Shopping cart. • Checkout. • Orders. • Invoice. • Django Admin. • Catalogue management.
Status: ⏳ Pending Live demo: ⏳ Pending ---

📝 Documentation Roadmap

🔧 Git & GitHub

Git is used for version control and project history. Typical workflow:

git status git add . git commit -m "Your commit message" git push origin main

Remote repository:

https://github.com/shaikhhabibali/ELECTROCART

The project follows a structured commit-and-push workflow during development. ---

📌 Project Status

ELECTROCART MW is an actively developed Django e-commerce application. The core catalogue foundation is established, including products, brands, categories, images, variants, specifications, pricing, stock, and catalogue validation. The project is now continuing toward a more automated and scalable catalogue ingestion architecture. ---

🗺️ Development Roadmap

P0  System Audit │ ▼ P1  Product Data Architecture │ ▼
P2  Source Research
│
▼
P3  Source Selection
│
▼
P4  Universal Data Format
│
▼
P5  Normalization
│
▼
P6  Duplicate Detection
│
▼
P7  Universal Importer
│
▼
P8  Image Automation
│
▼
P9  Variants + Specifications
│
▼
P10 Validation
│
▼
P11 Real Product Catalogue
│
▼
P12 Frontend Integration
│
▼
P13 Update System
│
▼
P14 Backup / Rollback
│
▼
P15 One-Command Catalogue

The roadmap is iterative and may be adjusted as implementation requirements evolve.

👨‍💻 Developer

Shaikh Habibali

📜 Project Notes

• ELECTROCART MW is maintained as the main project/workstream. • The catalogue architecture is designed for future extensibility. • External APIs and datasets are treated as potential data sources rather
than the application's permanent runtime database.
• Product and image data should be used only where the relevant source,
licensing, and usage conditions permit.
• Planned functionality is explicitly separated from implemented
functionality in this README. ---

⭐ Repository

ELECTROCART MW

https://github.com/shaikhhabibali/ELECTROCART

⚡ ELECTROCART

Technology for a Smarter Tomorrow.
