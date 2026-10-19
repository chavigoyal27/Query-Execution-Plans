import psycopg2

# Database configuration with default PostgreSQL port 5432
DB_PARAMS = {
    "host": "localhost",
    "database": "TPC-H",
    "user": "postgres",
    "password": "postgres",
    "port": "5432"
}

def drop_existing_tpch_tables(connection):
    """Drops existing TPC-H tables so schema changes can be reapplied safely."""
    sql_query = """
    DROP TABLE IF EXISTS public.lineitem CASCADE;
    DROP TABLE IF EXISTS public.orders CASCADE;
    DROP TABLE IF EXISTS public.partsupp CASCADE;
    DROP TABLE IF EXISTS public.customer CASCADE;
    DROP TABLE IF EXISTS public.supplier CASCADE;
    DROP TABLE IF EXISTS public.part CASCADE;
    DROP TABLE IF EXISTS public.nation CASCADE;
    DROP TABLE IF EXISTS public.region CASCADE;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Dropped existing TPC-H tables (if any).")


def create_region_table(connection):
    """Creates the public.region table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.region
    (
        r_regionkey integer NOT NULL,
        r_name character(25) COLLATE pg_catalog."default" NOT NULL,
        r_comment character varying(152) COLLATE pg_catalog."default",
        CONSTRAINT region_pkey PRIMARY KEY (r_regionkey)
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.region
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.region' created successfully.")


def create_nation_table(connection):
    """Creates the public.nation table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.nation
    (
        n_nationkey integer NOT NULL,
        n_name character(25) COLLATE pg_catalog."default" NOT NULL,
        n_regionkey integer NOT NULL,
        n_comment character varying(152) COLLATE pg_catalog."default",
        CONSTRAINT nation_pkey PRIMARY KEY (n_nationkey),
        CONSTRAINT fk_nation FOREIGN KEY (n_regionkey)
            REFERENCES public.region (r_regionkey) MATCH SIMPLE
            ON UPDATE NO ACTION
            ON DELETE NO ACTION
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.nation
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.nation' created successfully.")


def create_part_table(connection):
    """Creates the public.part table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.part
    (
        p_partkey integer NOT NULL,
        p_name character varying(55) COLLATE pg_catalog."default" NOT NULL,
        p_mfgr character(25) COLLATE pg_catalog."default" NOT NULL,
        p_brand character(10) COLLATE pg_catalog."default" NOT NULL,
        p_type character varying(25) COLLATE pg_catalog."default" NOT NULL,
        p_size integer NOT NULL,
        p_container character(10) COLLATE pg_catalog."default" NOT NULL,
        p_retailprice numeric(15,2) NOT NULL,
        p_comment character varying(23) COLLATE pg_catalog."default" NOT NULL,
        CONSTRAINT part_pkey PRIMARY KEY (p_partkey)
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.part
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.part' created successfully.")


def create_supplier_table(connection):
    """Creates the public.supplier table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.supplier
    (
        s_suppkey integer NOT NULL,
        s_name character(25) COLLATE pg_catalog."default" NOT NULL,
        s_address character varying(40) COLLATE pg_catalog."default" NOT NULL,
        s_nationkey integer NOT NULL,
        s_phone character(15) COLLATE pg_catalog."default" NOT NULL,
        s_acctbal numeric(15,2) NOT NULL,
        s_comment character varying(101) COLLATE pg_catalog."default" NOT NULL,
        CONSTRAINT supplier_pkey PRIMARY KEY (s_suppkey),
        CONSTRAINT fk_supplier FOREIGN KEY (s_nationkey)
            REFERENCES public.nation (n_nationkey) MATCH SIMPLE
            ON UPDATE NO ACTION
            ON DELETE NO ACTION
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.supplier
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.supplier' created successfully.")


def create_partsupp_table(connection):
    """Creates the public.partsupp table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.partsupp
    (
        ps_partkey integer NOT NULL,
        ps_suppkey integer NOT NULL,
        ps_availqty integer NOT NULL,
        ps_supplycost numeric(15,2) NOT NULL,
        ps_comment character varying(199) COLLATE pg_catalog."default" NOT NULL,
        CONSTRAINT partsupp_pkey PRIMARY KEY (ps_partkey, ps_suppkey)
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.partsupp
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.partsupp' created successfully.")


def create_customer_table(connection):
    """Creates the public.customer table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.customer
    (
        c_custkey integer NOT NULL,
        c_name character varying(25) COLLATE pg_catalog."default" NOT NULL,
        c_address character varying(40) COLLATE pg_catalog."default" NOT NULL,
        c_nationkey integer NOT NULL,
        c_phone character(15) COLLATE pg_catalog."default" NOT NULL,
        c_acctbal numeric(15,2) NOT NULL,
        c_mktsegment character(10) COLLATE pg_catalog."default" NOT NULL,
        c_comment character varying(117) COLLATE pg_catalog."default" NOT NULL,
        CONSTRAINT customer_pkey PRIMARY KEY (c_custkey),
        CONSTRAINT fk_customer FOREIGN KEY (c_nationkey)
            REFERENCES public.nation (n_nationkey) MATCH SIMPLE
            ON UPDATE NO ACTION
            ON DELETE NO ACTION
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.customer
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.customer' created successfully.")


def create_orders_table(connection):
    """Creates the public.orders table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.orders
    (
        o_orderkey integer NOT NULL,
        o_custkey integer NOT NULL,
        o_orderstatus character(1) COLLATE pg_catalog."default" NOT NULL,
        o_totalprice numeric(15,2) NOT NULL,
        o_orderdate date NOT NULL,
        o_orderpriority character(15) COLLATE pg_catalog."default" NOT NULL,
        o_clerk character(15) COLLATE pg_catalog."default" NOT NULL,
        o_shippriority integer NOT NULL,
        o_comment character varying(79) COLLATE pg_catalog."default" NOT NULL,
        CONSTRAINT orders_pkey PRIMARY KEY (o_orderkey)
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.orders
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.orders' created successfully.")


def create_lineitem_table(connection):
    """Creates the public.lineitem table in PostgreSQL."""
    sql_query = """
    CREATE TABLE public.lineitem
    (
        l_orderkey integer NOT NULL,
        l_partkey integer NOT NULL,
        l_suppkey integer NOT NULL,
        l_linenumber integer NOT NULL,
        l_quantity numeric(15,2) NOT NULL,
        l_extendedprice numeric(15,2) NOT NULL,
        l_discount numeric(15,2) NOT NULL,
        l_tax numeric(15,2) NOT NULL,
        l_returnflag character(1) COLLATE pg_catalog."default" NOT NULL,
        l_linestatus character(1) COLLATE pg_catalog."default" NOT NULL,
        l_shipdate date NOT NULL,
        l_commitdate date NOT NULL,
        l_receiptdate date NOT NULL,
        l_shipinstruct character(25) COLLATE pg_catalog."default" NOT NULL,
        l_shipmode character(10) COLLATE pg_catalog."default" NOT NULL,
        l_comment character varying(44) COLLATE pg_catalog."default" NOT NULL,
        CONSTRAINT lineitem_pkey PRIMARY KEY (l_orderkey, l_linenumber)
    )
    WITH (
        OIDS = FALSE
    )
    TABLESPACE pg_default;

    ALTER TABLE public.lineitem
        OWNER to postgres;
    """
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
    print("Table 'public.lineitem' created successfully.")


def main():
    try:
        connection = psycopg2.connect(**DB_PARAMS)

        drop_existing_tpch_tables(connection)

        # Execution sequence respecting foreign key dependencies
        create_region_table(connection)
        create_nation_table(connection)
        create_part_table(connection)
        create_supplier_table(connection)
        create_partsupp_table(connection)
        create_customer_table(connection)
        create_orders_table(connection)
        create_lineitem_table(connection)

        # Commit transaction
        connection.commit()

    except (Exception, psycopg2.Error) as error:
        print("Error while connecting to PostgreSQL or executing queries:", error)

    finally:
        if 'connection' in locals() and connection:
            connection.close()
            print("PostgreSQL connection closed.")

if __name__ == "__main__":
    main()