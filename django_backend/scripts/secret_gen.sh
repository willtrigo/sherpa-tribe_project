#!/bin/bash
# Django SECRET_KEY generator.

# Generate a random string of 50 characters using the specified character set
chars='abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)'

# Using /dev/urandom for cryptographically secure random generation
secret_key=$(tr -dc "$chars" </dev/urandom | head -c 50)

echo "$secret_key"
