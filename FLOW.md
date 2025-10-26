1. Create Publications at MASTER DB
```
# This need to be run using SQL client connected to the MASTER DB
CREATE PUBLICATION airbyte_pub FOR ALL TABLES;
CREATE PUBLICATION test_dbmate_pub FOR ALL TABLES;

# Verify the publication
SELECT * FROM pg_publication;
```
2. Create Replication Slot at MASTER DB
```
SELECT * FROM pg_create_logical_replication_slot('airbyte_slot','pgoutput' );
SELECT * FROM pg_create_logical_replication_slot('test_dbmate_slot','pgoutput' );

# Verify the publication

SELECT * FROM pg_replication_slots;
```

3. Taking Snapshot
4. Copy Snapshot to Encrypted Storage
5. Restore Snapshot
6. Create Subscription
```
- Check LSN from Logs with keyword Invalid Length
- Create Subscription from source database (connection is from source database)
airbyte
```
CREATE SUBSCRIPTION airbyte_sub
CONNECTION 'host=testing-replikasi-master.cfkdf7u4lstc.ap-southeast-1.rds.amazonaws.com user=root password=vGrnlMZJUuMzAybb dbname=airbyte'
PUBLICATION airbyte_pub
WITH (
       copy_data = false,
       create_slot = false,
       enabled = false,
       synchronous_commit = false,
       connect = true,
       slot_name = 'airbyte_slot'
);
```

test-dbmate
CREATE SUBSCRIPTION test_dbmate_sub
CONNECTION 'host=testing-replikasi-master.cfkdf7u4lstc.ap-southeast-1.rds.amazonaws.com user=root password=vGrnlMZJUuMzAybb dbname=test-dbmate'
PUBLICATION test_dbmate_pub
WITH (
       copy_data = false,
       create_slot = false,
       enabled = false,
       synchronous_commit = false,
       connect = true,
       slot_name = 'test_dbmate_slot'
);

- Check pg_replicatio_origin
```
SELECT * FROM pg_replication_origin;
```


Check status pg replication origin
```
-- Check the status of replication origins (shows active sessions)
SELECT * FROM pg_replication_origin_status;
```


- Assign pg_replication_origin to Subscription Use from unused pg_replication_origin
```
SELECT pg_replication_origin_advance ('pg_origin', 'LSN from LOGS’); //38E7/403FB58
SELECT pg_replication_origin_advance ('pg_148921862', '38E7/403FB58'); // for airbyte
SELECT pg_replication_origin_advance ('pg_148921864', '38E7/403FB58'); // for test-dbmate
```


- Enable Subscription
```
ALTER SUBSCRIPTION airbyte_sub ENABLE;
ALTER SUBSCRIPTION test_dbmate_sub ENABLE;
```
```

6. Monitor Subscription Lagging etc
7. Drop Connection to Master with Create Firewall, block all connection to Master DB and only accept from DB Replication, 
       - ini masih jalan, perlu di diskusikan dengan tim 
       - bisa di reboot
       - make sure no lagging (final)
7. Delete subscription at REPLICATION DB
python3.10 manage_subscriptions.py  delete
```
 ALTER subscription airbyte DISABLE;
 
 ALTER SUBSCRIPTION airbyte SET (slot_name = NONE);
 
 DROP SUBSCRIPTION airbyte; 
 ```

8. Delete Replication Slot at MASTER DB
python3.10 manage_publications.py  delete
```
SELECT * FROM pg_drop_replication_slot('airbyte_slot');
SELECT * FROM pg_drop_replication_slot('test_dbmate_slot');
```

9. Delete Publications at MASTER DB
python3.10 manage_publications.py  delete
```
DROP PUBLICATION airbyte_pub;
DROP PUBLICATION test_dbmate_pub;
```
10. Ganti route53 external-db-prod ke yang external-db-prod-encrypt