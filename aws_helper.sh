#!/bin/bash

# AWS Helper Script for RDS Encryption Migration
# This script provides commands for the manual AWS operations required during migration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
}

# Function to check if AWS CLI is installed
check_aws_cli() {
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    print_success "AWS CLI is installed"
}

# Function to create snapshot
create_snapshot() {
    local db_instance=$1
    local snapshot_id="${db_instance}-encryption-snapshot-$(date +%Y%m%d-%H%M%S)"
    
    print_header "Creating Snapshot"
    print_info "Source DB Instance: $db_instance"
    print_info "Snapshot ID: $snapshot_id"
    
    aws rds create-db-snapshot \
        --db-instance-identifier "$db_instance" \
        --db-snapshot-identifier "$snapshot_id"
    
    print_success "Snapshot creation initiated: $snapshot_id"
    print_info "Waiting for snapshot to complete..."
    
    aws rds wait db-snapshot-completed \
        --db-snapshot-identifier "$snapshot_id"
    
    print_success "Snapshot completed: $snapshot_id"
    echo "$snapshot_id"
}

# Function to copy snapshot with encryption
copy_snapshot_encrypted() {
    local source_snapshot=$1
    local kms_key_id=$2
    local target_snapshot="${source_snapshot}-encrypted"
    
    print_header "Copying Snapshot with Encryption"
    print_info "Source Snapshot: $source_snapshot"
    print_info "Target Snapshot: $target_snapshot"
    print_info "KMS Key: $kms_key_id"
    
    aws rds copy-db-snapshot \
        --source-db-snapshot-identifier "$source_snapshot" \
        --target-db-snapshot-identifier "$target_snapshot" \
        --kms-key-id "$kms_key_id" \
        --copy-tags
    
    print_success "Encrypted snapshot copy initiated: $target_snapshot"
    print_info "Waiting for snapshot copy to complete..."
    
    aws rds wait db-snapshot-completed \
        --db-snapshot-identifier "$target_snapshot"
    
    print_success "Encrypted snapshot completed: $target_snapshot"
    echo "$target_snapshot"
}

# Function to restore encrypted snapshot
restore_snapshot() {
    local snapshot_id=$1
    local target_db_instance=$2
    local db_subnet_group=$3
    local vpc_security_groups=$4
    local db_parameter_group=$5
    local db_instance_class=$6
    
    print_header "Restoring Encrypted Snapshot"
    print_info "Snapshot: $snapshot_id"
    print_info "Target DB Instance: $target_db_instance"
    print_info "Instance Class: $db_instance_class"
    print_info "Parameter Group: $db_parameter_group"
    
    aws rds restore-db-instance-from-db-snapshot \
        --db-instance-identifier "$target_db_instance" \
        --db-snapshot-identifier "$snapshot_id" \
        --db-instance-class "$db_instance_class" \
        --db-subnet-group-name "$db_subnet_group" \
        --vpc-security-group-ids "$vpc_security_groups" \
        --db-parameter-group-name "$db_parameter_group" \
        --publicly-accessible \
        --no-multi-az \
        --storage-type gp3
    
    print_success "Database restore initiated: $target_db_instance"
    print_info "Waiting for database to become available (this may take 10-20 minutes)..."
    
    aws rds wait db-instance-available \
        --db-instance-identifier "$target_db_instance"
    
    print_success "Database is now available: $target_db_instance"
    
    # Get endpoint
    local endpoint=$(aws rds describe-db-instances \
        --db-instance-identifier "$target_db_instance" \
        --query 'DBInstances[0].Endpoint.Address' \
        --output text)
    
    print_success "Database Endpoint: $endpoint"
}

# Function to get LSN from CloudWatch logs
get_lsn_from_logs() {
    local db_instance=$1
    local log_group="/aws/rds/instance/${db_instance}/postgresql"
    
    print_header "Getting LSN from CloudWatch Logs"
    print_info "Log Group: $log_group"
    
    aws logs filter-log-events \
        --log-group-name "$log_group" \
        --filter-pattern 'invalid record length' \
        --max-items 5 \
        --query 'events[*].message' \
        --output text
    
    print_info "Look for the LSN in the format: 0/XXXXXXXX"
}

# Function to check database status
check_db_status() {
    local db_instance=$1
    
    print_header "Checking Database Status"
    
    aws rds describe-db-instances \
        --db-instance-identifier "$db_instance" \
        --query 'DBInstances[0].[DBInstanceIdentifier,DBInstanceStatus,Endpoint.Address,StorageEncrypted]' \
        --output table
}

# Function to delete snapshot
delete_snapshot() {
    local snapshot_id=$1
    
    print_header "Deleting Snapshot"
    print_warning "This will permanently delete: $snapshot_id"
    
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        aws rds delete-db-snapshot \
            --db-snapshot-identifier "$snapshot_id"
        print_success "Snapshot deleted: $snapshot_id"
    else
        print_info "Deletion cancelled"
    fi
}

# Function to delete database
delete_database() {
    local db_instance=$1
    
    print_header "Deleting Database"
    print_warning "This will permanently delete: $db_instance"
    
    read -p "Create final snapshot? (yes/no): " create_snapshot
    read -p "Are you sure you want to delete? (yes/no): " confirm
    
    if [ "$confirm" = "yes" ]; then
        if [ "$create_snapshot" = "yes" ]; then
            local final_snapshot="${db_instance}-final-snapshot-$(date +%Y%m%d-%H%M%S)"
            aws rds delete-db-instance \
                --db-instance-identifier "$db_instance" \
                --final-db-snapshot-identifier "$final_snapshot"
            print_success "Database deletion initiated with final snapshot: $final_snapshot"
        else
            aws rds delete-db-instance \
                --db-instance-identifier "$db_instance" \
                --skip-final-snapshot
            print_success "Database deletion initiated without final snapshot"
        fi
    else
        print_info "Deletion cancelled"
    fi
}

# Function to run full migration workflow
full_migration_workflow() {
    local source_db=$1
    local target_db=$2
    local kms_key=$3
    local db_subnet_group=$4
    local vpc_security_groups=$5
    local db_parameter_group=$6
    local db_instance_class=$7
    
    print_header "Full Migration Workflow"
    print_info "Source DB: $source_db"
    print_info "Target DB: $target_db"
    
    # Step 1: Create snapshot
    print_info "Step 1: Creating snapshot..."
    snapshot_id=$(create_snapshot "$source_db")
    
    # Step 2: Copy with encryption
    print_info "Step 2: Copying snapshot with encryption..."
    encrypted_snapshot=$(copy_snapshot_encrypted "$snapshot_id" "$kms_key")
    
    # Step 3: Restore
    print_info "Step 3: Restoring encrypted snapshot..."
    restore_snapshot "$encrypted_snapshot" "$target_db" "$db_subnet_group" \
        "$vpc_security_groups" "$db_parameter_group" "$db_instance_class"
    
    print_success "Migration workflow completed!"
    print_info "Next steps:"
    print_info "1. Get LSN: ./aws_helper.sh get-lsn $target_db"
    print_info "2. Run: python rds_encryption_automation.py --config databases.json --action setup-target"
}

# Main menu
show_menu() {
    echo ""
    echo "=========================================="
    echo "RDS Encryption Migration - AWS Helper"
    echo "=========================================="
    echo ""
    echo "Commands:"
    echo "  create-snapshot <db-instance>                           - Create database snapshot"
    echo "  copy-snapshot <source-snapshot> <kms-key>               - Copy snapshot with encryption"
    echo "  restore <snapshot> <target-db> <subnet> <sg> <param> <class> - Restore encrypted snapshot"
    echo "  get-lsn <db-instance>                                   - Get LSN from CloudWatch logs"
    echo "  check-status <db-instance>                              - Check database status"
    echo "  delete-snapshot <snapshot-id>                           - Delete snapshot"
    echo "  delete-db <db-instance>                                 - Delete database"
    echo "  full-workflow <source> <target> <kms> <subnet> <sg> <param> <class> - Run complete workflow"
    echo ""
    echo "Examples:"
    echo "  ./aws_helper.sh create-snapshot mydb-prod"
    echo "  ./aws_helper.sh get-lsn mydb-encrypted"
    echo "  ./aws_helper.sh check-status mydb-prod"
    echo ""
}

# Main script logic
main() {
    check_aws_cli
    
    if [ $# -eq 0 ]; then
        show_menu
        exit 0
    fi
    
    command=$1
    shift
    
    case $command in
        create-snapshot)
            if [ $# -ne 1 ]; then
                print_error "Usage: $0 create-snapshot <db-instance>"
                exit 1
            fi
            create_snapshot "$1"
            ;;
        copy-snapshot)
            if [ $# -ne 2 ]; then
                print_error "Usage: $0 copy-snapshot <source-snapshot> <kms-key>"
                exit 1
            fi
            copy_snapshot_encrypted "$1" "$2"
            ;;
        restore)
            if [ $# -ne 6 ]; then
                print_error "Usage: $0 restore <snapshot> <target-db> <subnet> <security-groups> <param-group> <instance-class>"
                exit 1
            fi
            restore_snapshot "$1" "$2" "$3" "$4" "$5" "$6"
            ;;
        get-lsn)
            if [ $# -ne 1 ]; then
                print_error "Usage: $0 get-lsn <db-instance>"
                exit 1
            fi
            get_lsn_from_logs "$1"
            ;;
        check-status)
            if [ $# -ne 1 ]; then
                print_error "Usage: $0 check-status <db-instance>"
                exit 1
            fi
            check_db_status "$1"
            ;;
        delete-snapshot)
            if [ $# -ne 1 ]; then
                print_error "Usage: $0 delete-snapshot <snapshot-id>"
                exit 1
            fi
            delete_snapshot "$1"
            ;;
        delete-db)
            if [ $# -ne 1 ]; then
                print_error "Usage: $0 delete-db <db-instance>"
                exit 1
            fi
            delete_database "$1"
            ;;
        full-workflow)
            if [ $# -ne 7 ]; then
                print_error "Usage: $0 full-workflow <source-db> <target-db> <kms-key> <subnet> <security-groups> <param-group> <instance-class>"
                exit 1
            fi
            full_migration_workflow "$1" "$2" "$3" "$4" "$5" "$6" "$7"
            ;;
        *)
            print_error "Unknown command: $command"
            show_menu
            exit 1
            ;;
    esac
}

main "$@"
