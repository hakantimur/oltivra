# Room databases are instantiated reflectively (e.g. WorkManager used by the ads SDK); R8 must keep them
# or release builds crash at startup with "Failed to create an instance of androidx.work.impl.WorkDatabase".
-keep class * extends androidx.room.RoomDatabase { <init>(); }
-keep class androidx.work.impl.WorkDatabase_Impl { *; }
-keep class androidx.work.impl.** extends androidx.room.RoomDatabase { *; }
